"""Library grouping, song labels, and accessible multi-folder import."""
import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog
from media_backend import MediaError

FIELDS = ('title', 'artist', 'album', 'track', 'disc')
DEFAULT_FIELDS = ['track', 'title', 'artist', 'album']
AUDIO_EXTENSIONS = set('.wav .mp3 .flac .ogg .oga .opus .m4a .aac .wma .aiff .aif .au .snd .caf .wv .mka .webm .mid .midi'.split())


class MetadataCache:
    """Read tags off the UI thread; changed files invalidate their cached tags."""
    def __init__(self, read_metadata, normalize):
        self.read_metadata = read_metadata
        self.normalize = normalize
        self.entries = {}
        self.lock = threading.Lock()

    def load(self, paths, cancelled):
        records = []
        for path in paths:
            if cancelled.is_set():
                break
            try:
                stat = os.stat(path)
                signature = (stat.st_mtime_ns, stat.st_size)
                if not os.path.isfile(path):
                    continue
            except OSError:
                continue
            key = os.path.normcase(os.path.abspath(path))
            # Serialize probes so a superseded request cannot spawn a second
            # probe for the same file. No Tk calls or UI waits occur here.
            with self.lock:
                if cancelled.is_set():
                    break
                cached = self.entries.get(key)
                if cached is None or cached[0] != signature:
                    try:
                        tags = self.normalize(self.read_metadata(path))
                    except (OSError, MediaError):
                        # A transient probe failure must not become a successful
                        # cache entry that hides tags until the file changes.
                        records.append((path, {}))
                        continue
                    self.entries[key] = (signature, tags)
                records.append((path, dict(self.entries[key][1])))
        return records


def load_library_records(app, paths, ready, back=None):
    """Cancelable background load; only the latest request may open a view."""
    previous = app.__dict__.get('_library_load')
    if previous:
        previous['cancel']()
    cache = app.__dict__.get('_library_metadata_cache')
    if cache is None:
        cache = app._library_metadata_cache = MetadataCache(app.media.read_metadata, app._normalized_metadata)
    cancelled = threading.Event()
    result = queue.Queue()
    dialog = tk.Toplevel(app)
    dialog.title('Loading Library')
    dialog.transient(app)
    tk.Label(dialog, text='Reading library information. You can cancel or choose another library view.').pack(padx=16, pady=16)
    request = {'cancelled': cancelled}
    def cancel(event=None):
        cancelled.set()
        dialog.destroy()
        if app.__dict__.get('_library_load') is request:
            app._library_load = None
        return 'break'
    request['cancel'] = cancel
    app._library_load = request
    cancel_button = app.accessible_button(dialog, 'Cancel', cancel)
    cancel_button.pack(pady=8)
    cancel_button.focus_set()
    dialog.protocol('WM_DELETE_WINDOW', cancel)
    dialog.bind('<Escape>', cancel)
    def go_back(event=None):
        cancel()
        if back: back()
        return 'break'
    dialog.bind('<BackSpace>', go_back)
    dialog.bind('<Alt-Left>', go_back)
    def work():
        try: result.put((cache.load(paths, cancelled), None))
        except Exception as error: result.put((None, str(error)))
    threading.Thread(target=work, daemon=True).start()
    def finish():
        if cancelled.is_set() or app.__dict__.get('_library_load') is not request:
            return
        try: records, error = result.get_nowait()
        except queue.Empty:
            app.after(50, finish)
            return
        cancel()
        if error: app.announce('Could not read the library: ' + error)
        elif not records: app.announce('This library section has no available audio files.')
        else: ready(records)
    # A cached view usually finishes before this announcement is needed.
    def loading_notice():
        if not cancelled.is_set(): app.announce('Reading library information. The window is still available; Escape in the loading window cancels.')
    app.after(500, loading_notice)
    app.after(50, finish)


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
