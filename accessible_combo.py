"""Speak both highlighted dropdown choices and committed/typed values."""
import tkinter as tk


def bind_combobox(app, box, label, variable):
    pending = [None]
    last = [None]
    closed = [False]

    def announce(value, focus=False):
        if pending[0] is not None:
            app.after_cancel(pending[0])
        def speak():
            pending[0] = None
            if closed[0]: return
            if focus and app.focus_get() is not box: return
            text = f'{label}, combo box, current value {value or "blank"}.' if focus else f'{label}, {value or "blank"}.'
            if focus or text != last[0]:
                last[0] = text
                app.screen_reader.speak(text)
        pending[0] = app.after(40, speak)

    def changed(*args):
        announce(variable.get().strip())

    box.bind('<FocusIn>', lambda event: announce(variable.get().strip(), True), add='+')
    box.bind('<<ComboboxSelected>>', changed, add='+')
    trace = variable.trace_add('write', changed)

    # Arrow keys in an open ttk dropdown belong to its separate Tcl Listbox.
    # The combobox variable does not change until Enter commits the choice.
    popdown = box.tk.call('ttk::combobox::PopdownWindow', str(box))
    def find_list(path):
        for child in box.tk.splitlist(box.tk.call('winfo', 'children', path)):
            if box.tk.call('winfo', 'class', child) == 'Listbox': return child
            found = find_list(child)
            if found: return found
        return None
    listing = find_list(popdown)
    if listing:
        def highlighted():
            if closed[0]: return
            indices = box.tk.splitlist(box.tk.call(listing, 'curselection'))
            if indices:
                announce(str(box.tk.call(listing, 'get', indices[0])))
        command = box.register(highlighted)
        for sequence in ('<<ListboxSelect>>', '<KeyRelease>', '<ButtonRelease-1>', '<Motion>'):
            box.tk.call('bind', listing, sequence, '+' + command)

    def cleanup(event):
        if event.widget is not box: return
        closed[0] = True
        if pending[0] is not None:
            app.after_cancel(pending[0]); pending[0] = None
        variable.trace_remove('write', trace)
    box.bind('<Destroy>', cleanup, add='+')
