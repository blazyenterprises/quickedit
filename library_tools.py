"""Library grouping, song labels, and accessible multi-folder import."""
import os
import json
import re
import sqlite3
from contextlib import closing
import queue
import threading
import tkinter as tk
from tkinter import filedialog
from media_backend import MediaError

FIELDS = ('title', 'artist', 'album', 'track', 'disc')
DEFAULT_FIELDS = ['track', 'title', 'artist', 'album']
AUDIO_EXTENSIONS = set('.wav .mp3 .flac .ogg .oga .opus .m4a .aac .wma .aiff .aif .au .snd .caf .wv .mka .webm .mid .midi'.split())


class MetadataCache:
    """Persistent catalog; browsing never stats or probes the audio files."""
    def __init__(self, read_metadata, normalize, database=None):
        self.read_metadata = read_metadata
        self.normalize = normalize
        self.entries = {}
        self.lock = threading.Lock()
        self.probe_lock = threading.Lock()
        self.pending = set()
        self.jobs = queue.Queue()
        self.worker = None
        self.database = database
        self.error = None
        if database:
            try:
                os.makedirs(os.path.dirname(database), exist_ok=True)
                with closing(sqlite3.connect(database)) as db, db:
                    db.execute('CREATE TABLE IF NOT EXISTS tracks (path TEXT PRIMARY KEY, mtime INTEGER, size INTEGER, tags TEXT)')
                    for path, mtime, size, raw in db.execute('SELECT path, mtime, size, tags FROM tracks'):
                        try:
                            tags = json.loads(raw)
                            if isinstance(tags, dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in tags.items()):
                                self.entries[path] = ((mtime, size), tags)
                        except (ValueError, TypeError):
                            pass
            except (OSError, sqlite3.Error) as error:
                self.error = str(error)

    @staticmethod
    def key(path):
        return os.path.normcase(os.path.abspath(path))

    def snapshot(self, paths):
        # The lock is never held while probing files or writing the database.
        with self.lock:
            cached = {self.key(p): self.entries.get(self.key(p)) for p in paths}
        return [(p, dict(cached[self.key(p)][1]) if cached[self.key(p)] else self.fallback(p)) for p in paths]

    @staticmethod
    def fallback(path):
        stem = os.path.splitext(os.path.basename(path))[0]
        tags = {'title': stem, 'album': os.path.basename(os.path.dirname(path)) or 'Unknown album'}
        match = re.match(r'^(\d{1,3})[ ._-]+(.+)$', stem)
        if match:
            tags.update(track=str(int(match[1])), title=match[2])
        return tags

    def store(self, path, signature, tags):
        key = self.key(path)
        with self.lock:
            self.entries[key] = (signature, dict(tags))
        if self.database:
            try:
                with closing(sqlite3.connect(self.database)) as db, db:
                    db.execute('INSERT OR REPLACE INTO tracks VALUES (?, ?, ?, ?)',
                               (key, signature[0], signature[1], json.dumps(tags)))
            except (OSError, sqlite3.Error) as error:
                self.error = str(error)

    def load(self, paths, cancelled, refresh=False):
        """Index selected paths on a worker; retain tags if a probe fails."""
        records = []
        for path in paths:
            if cancelled.is_set(): break
            try:
                stat = os.stat(path)
                signature = (stat.st_mtime_ns, stat.st_size)
                if not os.path.isfile(path): continue
            except OSError:
                continue
            key = self.key(path)
            with self.probe_lock:
                if cancelled.is_set(): break
                with self.lock: cached = self.entries.get(key)
                if refresh or cached is None or cached[0] != signature:
                    try:
                        tags = self.normalize(self.read_metadata(path))
                    except (OSError, MediaError) as error:
                        self.error = str(error)
                        records.append((path, dict(cached[1]) if cached else {}))
                        continue
                    self.store(path, signature, tags)
                    cached = (signature, tags)
                records.append((path, dict(cached[1])))
        return records

    def index_async(self, paths, refresh=False):
        with self.lock:
            if refresh: self.error = None
            for path in paths:
                key = self.key(path)
                if key not in self.pending and (refresh or key not in self.entries):
                    self.pending.add(key)
                    self.jobs.put((path, refresh))
            if self.pending and (self.worker is None or not self.worker.is_alive()):
                self.worker = threading.Thread(target=self._index_worker, daemon=True)
                self.worker.start()

    def _index_worker(self):
        while True:
            with self.lock:
                try: path, refresh = self.jobs.get_nowait()
                except queue.Empty:
                    self.worker = None
                    return
            try:
                if not self.load([path], threading.Event(), refresh):
                    self.error = 'Some library files are unavailable.'
            except Exception as error:
                self.error = str(error)
            finally:
                with self.lock: self.pending.discard(self.key(path))


def library_catalog(app):
    cache = app.__dict__.get('_library_metadata_cache')
    if cache is None:
        history = getattr(app, '_history_path', None)
        database = os.path.join(os.path.dirname(history), 'library.sqlite3') if isinstance(history, str) else None
        cache = app._library_metadata_cache = MetadataCache(app.media.read_metadata, app._normalized_metadata, database)
    return cache


def index_library(app, refresh=False):
    cache = library_catalog(app)
    cache.index_async(list(app.library_files), refresh)
    if refresh:
        app.announce('Updating library information in the background. Browsing and playback remain available. Reopen a view to see updated information.')


def library_index_status(app):
    cache = library_catalog(app)
    with cache.lock: count = len(cache.pending)
    message = f'Library information is updating. {count} songs remaining.' if count else 'Library information is up to date. Reopen a view to see updates.'
    if cache.error: message += ' Some information could not be saved or read. Use Refresh Library Information to retry.'
    app.announce(message)


def load_library_records(app, paths, ready, back=None):
    """Show a catalog snapshot immediately; index only unknown songs in background."""
    cache = library_catalog(app)
    records = cache.snapshot(paths)
    cache.index_async(paths)
    if records: ready(records)
    else: app.announce('This library section has no songs.')


def bind_first_letter_navigation(widget, names):
    """Cycle by the actual name, regardless of the spoken display fields."""
    names = [name.lstrip().casefold() for name in names]
    def navigate(event):
        char = event.char
        if not char or not char.isalnum() or event.state & (0x0004 | 0x0008 | 0x20000):
            return None
        selected = widget.curselection()
        start = selected[0] if selected else -1
        for offset in range(1, len(names) + 1):
            index = (start + offset) % len(names)
            if names[index].startswith(char.casefold()):
                widget.selection_clear(0, 'end')
                widget.selection_set(index)
                widget.activate(index)
                widget.see(index)
                widget.event_generate('<<ListboxSelect>>')
                break
        return 'break'
    widget.bind('<KeyPress>', navigate, add='+')


def bind_folder_announcements(widget, name, speak):
    """Speak the active row after Tk finishes its selection/cursor updates."""
    pending = [None]
    last = [None]
    entering = [False]
    def announce():
        pending[0] = None
        if not widget.winfo_exists() or not widget.size():
            return
        active = widget.index('active')
        selected = tuple(widget.curselection())
        state = (active, selected, widget.get(active))
        if state == last[0]:
            return
        last[0] = state
        text = (name + '. ' if entering[0] else '') + widget.get(active)
        entering[0] = False
        if len(selected) > 1:
            text += f'. {len(selected)} folders selected.'
        elif active not in selected:
            text += '. Not selected.'
        speak(text)
    def schedule(event=None):
        if pending[0] is not None:
            widget.after_cancel(pending[0])
        pending[0] = widget.after_idle(announce)
    def focus(event=None):
        last[0] = None
        entering[0] = True
        schedule()
    widget.bind('<<ListboxSelect>>', schedule)
    widget.bind('<KeyRelease>', schedule)
    widget.bind('<ButtonRelease-1>', schedule)
    widget.bind('<FocusIn>', focus)
    return schedule


def valid_fields(value):
    if not isinstance(value, list):
        return DEFAULT_FIELDS.copy()
    result = list(dict.fromkeys(x for x in value if isinstance(x, str) and x in FIELDS))
    return result if 'title' in result else DEFAULT_FIELDS.copy()


def song_label(tags, path, fields):
    values = dict(tags)
    values['title'] = tags.get('title') or os.path.splitext(os.path.basename(path))[0]
    values['artist'] = tags.get('artist') or 'Unknown artist'
    values['album'] = tags.get('album') or 'Unknown album'
    values['track'] = 'Track ' + (tags.get('track') or 'unknown')
    values['disc'] = 'Disc ' + (tags.get('disc') or '1')
    return '; '.join(values[field] for field in valid_fields(fields))


def group_records(records, category):
    groups = {}
    for path, tags in records:
        artist = tags.get('artist') or 'Unknown artist'
        album = tags.get('album') or 'Unknown album'
        owner = tags.get('album_artist') or tags.get('albumartist') or artist
        key = (artist.casefold(),) if category == 'artist' else (album.casefold(), owner.casefold())
        label = artist if category == 'artist' else album
        if key not in groups:
            groups[key] = [label, [], owner]
        groups[key][1].append(path)
    # Only add the album artist when needed to distinguish identical album names.
    counts = {}
    for label, _, _ in groups.values():
        counts[label.casefold()] = counts.get(label.casefold(), 0) + 1
    return sorted([(label + (f'; {owner}' if category == 'album' and counts[label.casefold()] > 1 else ''), paths)
                   for label, paths, owner in groups.values()], key=lambda item: item[0].casefold())


def scan_folders(folders):
    paths, errors, seen = [], [], set()
    for folder in folders:
        if not os.path.isdir(folder):
            errors.append(f'Folder unavailable: {folder}')
            continue
        for root, dirs, files in os.walk(folder, onerror=lambda error: errors.append(str(error)), followlinks=False):
            dirs[:] = sorted(d for d in dirs if not os.path.islink(os.path.join(root, d)) and not os.path.isjunction(os.path.join(root, d)))
            for name in sorted(files):
                path = os.path.abspath(os.path.join(root, name))
                key = os.path.normcase(path)
                if os.path.splitext(name)[1].lower() in AUDIO_EXTENSIONS and key not in seen:
                    seen.add(key)
                    paths.append(path)
    return paths, errors


def choose_folders(app):
    dialog = tk.Toplevel(app)
    dialog.title('Add Folders to Library')
    dialog.transient(app)
    dialog.grab_set()
    location = tk.StringVar(value=app.last_open_directory or os.path.expanduser('~'))
    tk.Label(dialog, text='Folder location. Enter a path and press Enter to list its folders.').pack(anchor='w')
    entry = tk.Entry(dialog, textvariable=location, width=90)
    entry.pack(fill='x')
    entry.bind('<FocusIn>', lambda event: app.screen_reader.speak('Folder location, edit. ' + location.get()))
    tk.Label(dialog, text='Folders: use Control or Shift with arrows to select multiple; Control+A selects all.').pack(anchor='w')
    choices = tk.Listbox(dialog, selectmode='extended', exportselection=False, width=90, height=14)
    choices.pack(fill='both', expand=True)
    children, basket = [], []
    status = tk.StringVar(value='No folders queued.')
    tk.Label(dialog, textvariable=status).pack(anchor='w')
    pending = tk.Listbox(dialog, selectmode='extended', exportselection=False, width=90, height=5)
    pending.pack(fill='x')
    def speak(text):
        status.set(text)
        app.screen_reader.speak(text)
    def refresh(event=None):
        try:
            root = os.path.abspath(os.path.expanduser(location.get()))
            with os.scandir(root) as entries:
                found = sorted((e.path for e in entries if e.is_dir()), key=str.casefold)
        except OSError as error:
            speak(str(error)); return 'break'
        location.set(root)
        children[:] = found
        choices.delete(0, 'end')
        for path in children: choices.insert('end', os.path.basename(path))
        if children:
            choices.selection_set(0)
            choices.activate(0)
            choices.selection_anchor(0)
        choices.focus_set()
        speak(f'{root}. {len(children)} folders.')
        return 'break'
    def browse():
        path = filedialog.askdirectory(parent=dialog, initialdir=location.get())
        if path: location.set(path); refresh()
    def open_folder(event=None):
        selected = choices.curselection()
        if selected: location.set(children[selected[0]]); refresh()
        return 'break'
    def add(paths):
        for path in paths:
            if os.path.isdir(path) and os.path.normcase(path) not in {os.path.normcase(p) for p in basket}:
                basket.append(path); pending.insert('end', path)
        choices.selection_clear(0, 'end')
        speak(f'{len(basket)} folders queued, including all their subfolders.')
    def remove():
        for index in reversed(pending.curselection()):
            del basket[index]; pending.delete(index)
        speak(f'{len(basket)} folders queued.')
    def import_all():
        selected = [children[i] for i in choices.curselection()]
        folders = list({os.path.normcase(os.path.abspath(path)): path for path in basket + selected}.values())
        if not folders: speak('Select folders or queue the current folder first.'); return
        app.last_open_directory = location.get()
        dialog.destroy()
        app.announce('Scanning folders for audio files.')
        results = queue.Queue()
        def scan():
            try: results.put(scan_folders(folders))
            except Exception as error: results.put(([], [str(error)]))
        threading.Thread(target=scan, daemon=True).start()
        def finish():
            try: paths, errors = results.get_nowait()
            except queue.Empty: app.after(100, finish); return
            if paths: app._add_library_paths(paths)
            else: app.announce('No supported audio files found.')
            if errors: app.announce(f'{len(errors)} folders could not be fully read. {errors[0]}')
        app.after(100, finish)
    buttons = tk.Frame(dialog); buttons.pack(fill='x')
    for label, command in [('Browse Location', browse), ('Up One Folder', lambda: (location.set(os.path.dirname(location.get())), refresh())),
                           ('Open Selected Folder', open_folder), ('Queue Selected Folders', lambda: add([children[i] for i in choices.curselection()])),
                           ('Queue Current Folder', lambda: add([location.get()])), ('Remove Queued Folders', remove),
                           ('Import Folders', import_all), ('Cancel', dialog.destroy)]:
        app.accessible_button(buttons, label, command).pack(anchor='w')
    entry.bind('<Return>', refresh)
    choices.bind('<Return>', open_folder)
    choices.bind('<Double-Button-1>', open_folder)
    def select_all(event): choices.selection_set(0, 'end'); speak(f'All {len(children)} folders selected.'); return 'break'
    choices.bind('<Control-a>', select_all)
    for widget, name in [(choices, 'Available folders'), (pending, 'Queued folders')]:
        bind_folder_announcements(widget, name, app.screen_reader.speak)
    dialog.bind('<Escape>', lambda event: dialog.destroy())
    refresh()


def configure_display(app):
    dialog = tk.Toplevel(app); dialog.title('Song Information Display'); dialog.transient(app); dialog.grab_set()
    fields = valid_fields(app.__dict__.get('library_display_fields'))
    tk.Label(dialog, text='Information shown in songs, in reading order. Title is always included.').pack()
    choices = tk.Listbox(dialog, exportselection=False, width=55, height=8); choices.pack(fill='both')
    def refresh(index=0):
        choices.delete(0, 'end')
        for field in fields: choices.insert('end', field.title())
        choices.selection_set(index); choices.activate(index)
    def move(delta):
        selected = choices.curselection()
        if selected and 0 <= selected[0] + delta < len(fields):
            i = selected[0]; j = i + delta
            fields[i], fields[j] = fields[j], fields[i]; refresh(j)
            app.screen_reader.speak(f'{fields[j]}. Position {j + 1}.')
    def toggle(field):
        if field in fields: fields.remove(field)
        else: fields.append(field)
        refresh()
        app.screen_reader.speak(f'{field} ' + ('shown' if field in fields else 'hidden'))
    for field in FIELDS[1:]:
        value = tk.BooleanVar(value=field in fields)
        button = tk.Checkbutton(dialog, text='Show ' + field, variable=value, command=lambda f=field: toggle(f))
        button.bind('<FocusIn>', lambda event, field=field, value=value: app.screen_reader.speak(
            'Show ' + field + ', checkbox, ' + ('checked' if value.get() else 'unchecked')))
        button._value = value
        button.pack(anchor='w')
    def save():
        app.library_display_fields = fields.copy(); app._save_file_history(); dialog.destroy(); app.announce('Song information display saved.')
    for label, command in [('Move Earlier', lambda: move(-1)), ('Move Later', lambda: move(1)), ('Save', save), ('Cancel', dialog.destroy)]:
        app.accessible_button(dialog, label, command).pack(anchor='w')
    choices.bind('<<ListboxSelect>>', lambda event: app.screen_reader.speak(choices.get(choices.curselection()[0])) if choices.curselection() else None)
    choices.bind('<FocusIn>', lambda event: app.screen_reader.speak('Song information reading order'))
    dialog.bind('<Escape>', lambda event: dialog.destroy())
    refresh(); choices.focus_set()
