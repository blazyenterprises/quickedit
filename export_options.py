"""Keyboard-accessible output options used by Save As."""
import os
import tkinter as tk
from tkinter import ttk, messagebox
from media_backend import MediaError, validate_export_depth, validate_export_rate


def validate_options(values):
    try:
        rate, depth, channels, bitrate = (int(value) for value in values)
    except ValueError:
        raise ValueError('Enter whole numbers for all output settings.') from None
    if not 1000 <= rate <= 384000:
        raise ValueError('Sample rate must be between 1,000 and 384,000 Hertz.')
    if depth not in (8, 16, 24, 32):
        raise ValueError('PCM bit depth must be 8, 16, 24, or 32.')
    if not 1 <= channels <= 8:
        raise ValueError('Channels must be between 1 and 8. Mono is 1; stereo is 2.')
    if not 8 <= bitrate <= 1536:
        raise ValueError('Compressed bitrate must be between 8 and 1,536 kilobits per second.')
    return rate, depth, channels, bitrate


def choose_options(app, path, defaults):
    if os.path.splitext(path)[1].lower() in {'.opus', '.webm'} and defaults[0] not in {8000, 12000, 16000, 24000, 48000}:
        defaults = (48000, *defaults[1:])
    previous_grab = app.grab_current()
    previous_grab_status = previous_grab.grab_status() if previous_grab is not None else None
    previous_focus = app.focus_get()
    dialog = tk.Toplevel(app)
    dialog.title('Save As — Output Settings')
    dialog.transient(app); dialog.grab_set()
    tk.Label(dialog, text=f'Save {os.path.basename(path)}\nReview the output settings, then choose Save Audio.').grid(row=0, column=0, sticky='w', padx=12, pady=12)
    specs = [
        ('Sample rate in Hertz', (8000, 16000, 22050, 44100, 48000, 96000, 192000)),
        ('PCM bit depth', (8, 16, 24, 32)),
        ('Channels; 1 mono, 2 stereo', (1, 2, 4, 6, 8)),
        ('Compressed bitrate in kilobits per second', (32, 64, 96, 128, 160, 192, 256, 320)),
    ]
    variables, boxes, result = [], [], []
    for index, ((label, choices), default) in enumerate(zip(specs, defaults)):
        tk.Label(dialog, text=label).grid(row=index * 2 + 1, column=0, sticky='w', padx=12)
        value = tk.StringVar(value=str(default))
        box = ttk.Combobox(dialog, textvariable=value, values=choices, state='normal', takefocus=True, width=48)
        box.grid(row=index * 2 + 2, column=0, sticky='ew', padx=12, pady=(0, 8))
        app.bind_accessible_combobox(box, label, value)
        variables.append(value); boxes.append(box)
    tk.Label(dialog, text='Bitrate applies to supported compressed formats. PCM bit depth applies to formats that support it.').grid(row=9, column=0, sticky='w', padx=12)
    def save():
        try:
            options = validate_options([value.get() for value in variables])
            validate_export_depth(os.path.splitext(path)[1], options[1])
            validate_export_rate(os.path.splitext(path)[1], options[0])
        except (ValueError, MediaError) as error:
            messagebox.showerror('Invalid output settings', str(error), parent=dialog)
            boxes[0].focus_set()
            return
        result.append(options); dialog.destroy()
    buttons = tk.Frame(dialog); buttons.grid(row=10, column=0, sticky='ew', padx=12, pady=12)
    app.accessible_button(buttons, 'Save Audio', save).pack(side='left')
    app.accessible_button(buttons, 'Cancel Save', dialog.destroy).pack(side='right')
    # Enter remains available to accept a combobox choice; saving is explicit.
    dialog.bind('<Escape>', lambda event: dialog.destroy())
    dialog.protocol('WM_DELETE_WINDOW', dialog.destroy)
    dialog.columnconfigure(0, weight=1)
    boxes[0].focus_set()
    try:
        app.wait_window(dialog)
    finally:
        # Save As can be reached from an unsaved-changes prompt while another
        # modal (such as the library picker) is still open underneath it.
        try:
            if previous_grab is not None and previous_grab.winfo_exists():
                if previous_grab_status == 'global':
                    previous_grab.grab_set_global()
                else:
                    previous_grab.grab_set()
            if previous_focus is not None and previous_focus.winfo_exists():
                previous_focus.focus_set()
        except tk.TclError:
            pass  # The application may have been closed during the wait.
    return result[0] if result else None
