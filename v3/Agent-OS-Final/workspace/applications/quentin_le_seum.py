import sys
import tkinter as tk
from tkinter import messagebox

MESSAGE = "Quentin le seum"

def main():
    if '--self-test' in sys.argv:
        if not MESSAGE:
            raise RuntimeError('Message vide')
        print('AGENTOS_SELF_TEST_OK')
        print(MESSAGE)
        return

    root = tk.Tk()
    root.withdraw()
    try:
        messagebox.showinfo('Message', MESSAGE)
    finally:
        root.destroy()

if __name__ == '__main__':
    main()
