# modules/viewer/modern_pdf_viewer.py

import tkinter as tk
from tkinter import messagebox, ttk
from PIL import Image, ImageTk
import fitz
import io, os, sys
from collections import OrderedDict
import platform
import tempfile
import webbrowser
try:
    import win32com.client  # optional: nur für Outlook-Entwurf
except Exception:
    win32com = None


def _c(d, k, fallback):
    """Sicherer Dict-Zugriff mit Fallback"""
    try:
        return d.get(k, fallback) if isinstance(d, dict) else fallback
    except:
        return fallback


class ActionRow(ttk.Frame):
    """Moderne Action-Zeile mit Hover-Effekten und aktiv-Status"""
    def __init__(self, master, text, icon=None, accent="#2563EB", command=None, *args, **kwargs):
        super().__init__(master, *args, **kwargs)
        self.command = command
        self.accent_color = accent
        self.active = False

        bg_default = master.cget("background") if master and master.cget("background") else "#111827"
        self._bg_default = bg_default
        self._bg_hover   = "#162032"
        self._bg_active  = "#13253F"

        self.configure(padding=0)
        self._container = tk.Frame(self, bg=self._bg_default, cursor="hand2")
        self._container.pack(fill="x", expand=True)

        self._accent = tk.Frame(self._container, width=3, bg=self._bg_default)
        self._accent.pack(side="left", fill="y")

        self._click = tk.Frame(self._container, bg=self._bg_default)
        self._click.pack(side="left", fill="x", expand=True)

        self._icon_wrap = tk.Frame(self._click, bg=self._bg_default, width=28)
        self._icon_wrap.pack(side="left", padx=(12,8), pady=8, fill="y")
        self._icon_wrap.pack_propagate(False)

        if isinstance(icon, tk.PhotoImage):
            self._icon = tk.Label(self._icon_wrap, image=icon, bg=self._bg_default, bd=0)
        else:
            icon_text = icon if isinstance(icon, str) else "•"
            self._icon = tk.Label(self._icon_wrap, text=icon_text, bg=self._bg_default,
                                  fg="#E5E7EB", font=("Segoe UI", 10, "bold"))
        self._icon.pack(expand=True)

        self._label = tk.Label(self._click, text=text, bg=self._bg_default, fg="#E5E7EB", font=("Segoe UI", 10, "bold"))
        self._label.pack(side="left", padx=(0,12), pady=8)

        for w in (self._container, self._click, self._icon_wrap, self._icon, self._label):
            w.bind("<Enter>", self._on_enter)
            w.bind("<Leave>", self._on_leave)
            w.bind("<Button-1>", self._on_click)
            w.bind("<Button-3>", lambda e: None)

    def set_active(self, active: bool):
        self.active = active
        bg = self._bg_active if active else self._bg_default
        for w in (self._container, self._click, self._icon_wrap, self._icon, self._label):
            w.configure(bg=bg)
        self._accent.configure(bg=self.accent_color if active else bg)

    def _on_enter(self, _):
        if not self.active:
            for w in (self._container, self._click, self._icon_wrap, self._icon, self._label):
                w.configure(bg=self._bg_hover)

    def _on_leave(self, _):
        if not self.active:
            for w in (self._container, self._click, self._icon_wrap, self._icon, self._label):
                w.configure(bg=self._bg_default)

    def _on_click(self, _):
        if callable(self.command):
            self.command()


class ModernPDFViewer:
    def __init__(self, root, settings, pdf_path):
        self.root = root
        self.settings = settings
        self.pdf_path = pdf_path
        self.pdf_document = None
        self.current_page = 0
        self.total_pages = 0

        self.current_page_image = None
        self._page_photo = None
        self.thumbnail_cache = OrderedDict()
        self.max_thumb_cache = 200
        self._thumb_photos_by_button = {}

        self.base_zoom = 1.5
        self.zoom = self.base_zoom
        self.min_zoom = 0.4
        self.max_zoom = 6.0
        self.fit_to_window = True

        self._thumb_batch_idx = 0
        self._thumb_buttons = []
        self._thumb_batch_size = 8
        self._thumb_target_size = (140, 180)

        self._redactions_by_page = {}
        self._texts_by_page = {}
        self._selected_text = None

        self.colors = {
            'bg_primary':   '#1a1a2e',
            'bg_secondary': '#1a1a2e',
            'text_primary': '#ffffff',
            'text_secondary':'#9ca3af',
            'text_muted':   '#6b7280',
            'button_bg':    '#2a2a3e',
            'button_hover': '#3a3a4e',
            'pane_bg':      '#0F172A',
            'card_bg':      '#111827',
            'border':       '#1E293B',
            'accent':       '#2563EB',
            'muted':        '#94A3B8',
        }

        # UI-Auswahl (Tk-Font) → PDF-Export (Base-14) Mapping
        self._font_map = OrderedDict({
            "Sans (Helvetica)":        ("Helvetica",       "helv"),
            "Serif (Times)":           ("Times New Roman", "times"),
            "Mono (Courier)":          ("Courier New",     "cour"),
        })

        self.load_pdf()
        self.create_seamless_layout(self.root)
        self.display_page()
        self.bind_events()

    def load_pdf(self):
        """PDF-Dokument laden"""
        try:
            self.pdf_document = fitz.open(self.pdf_path)
            self.total_pages = len(self.pdf_document)
        except Exception as e:
            messagebox.showerror("PDF öffnen fehlgeschlagen", str(e))
            raise

    def create_seamless_layout(self, parent):
        """Hauptlayout erstellen"""
        try:
            self.root.title(f"Modern PDF Viewer - {os.path.basename(self.pdf_path)}")
            self.root.state('zoomed')
        except:
            try:
                if platform.system() == "Linux":
                    self.root.attributes('-zoomed', True)
            except:
                pass

        try:
            self.root.configure(bg=self.colors['bg_primary'])
        except:
            pass

        main_container = tk.Frame(self.root, bg=self.colors['bg_primary'])
        main_container.pack(fill='both', expand=True)

        # LEFT: THUMBNAILS
        self.sidebar_frame = tk.Frame(main_container, bg=self.colors['bg_primary'], width=190)
        self.sidebar_frame.pack(side=tk.LEFT, fill='y')
        self.sidebar_frame.pack_propagate(False)

        title_frame = tk.Frame(self.sidebar_frame, bg=self.colors['bg_primary'], height=60)
        title_frame.pack(fill='x')
        title_frame.pack_propagate(False)

        title_label = tk.Label(title_frame, text="📄 SEITEN", font=('Segoe UI', 14, 'bold'),
                               bg=self.colors['bg_primary'], fg=self.colors['text_primary'])
        title_label.pack(pady=20)

        self.thumb_frame = tk.Frame(self.sidebar_frame, bg=self.colors['bg_primary'])
        self.thumb_frame.pack(fill='both', expand=True, padx=15, pady=(0, 20))

        self.thumb_canvas = tk.Canvas(self.thumb_frame, bg=self.colors['bg_primary'],
                                      highlightthickness=0, scrollregion=(0, 0, 0, 0), bd=0)

        self.thumb_scrollbar = tk.Scrollbar(self.thumb_frame, orient="vertical",
                                            command=self.thumb_canvas.yview, width=10)
        self.thumb_canvas.configure(yscrollcommand=self.thumb_scrollbar.set)
        self.thumb_scrollbar.pack(side="right", fill="y")
        self.thumb_canvas.pack(side="left", fill="both", expand=True)

        self.thumb_inner = tk.Frame(self.thumb_canvas, bg=self.colors['bg_primary'])
        self.thumb_canvas.create_window((0, 0), window=self.thumb_inner, anchor="nw")

        self.thumb_canvas.bind('<Configure>', self._on_thumb_canvas_configure)
        self.thumb_inner.bind("<Configure>",
            lambda e: self.thumb_canvas.configure(scrollregion=self.thumb_canvas.bbox("all")))

        self._build_thumbnail_placeholders()
        self._schedule_thumb_batch()

        # MIDDLE: PDF
        self.pdf_frame = tk.Frame(main_container, bg=self.colors['bg_primary'])
        self.pdf_frame.pack(side=tk.LEFT, fill='both', expand=True)

        self.v_scroll = tk.Scrollbar(self.pdf_frame, orient="vertical", width=12, command=None)
        self.h_scroll = tk.Scrollbar(self.pdf_frame, orient="horizontal", width=12, command=None)

        self.pdf_canvas = tk.Canvas(self.pdf_frame, bg=self.colors['bg_primary'], highlightthickness=0,
                                    yscrollcommand=self.v_scroll.set, xscrollcommand=self.h_scroll.set, bd=0)

        self.v_scroll.config(command=self.pdf_canvas.yview)
        self.h_scroll.config(command=self.pdf_canvas.xview)

        self.pdf_canvas.grid(row=0, column=0, sticky="nsew")
        self.v_scroll.grid(row=0, column=1, sticky="ns")
        self.h_scroll.grid(row=1, column=0, sticky="ew")

        self.pdf_frame.rowconfigure(0, weight=1)
        self.pdf_frame.columnconfigure(0, weight=1)

        # RIGHT: ACTIONS
        pane_bg = _c(self.colors, "pane_bg", "#0F172A")
        card_bg = _c(self.colors, "card_bg", "#111827")
        border  = _c(self.colors, "border",  "#1E293B")
        accent  = _c(self.colors, "accent",  "#2563EB")
        muted   = _c(self.colors, "muted",   "#94A3B8")

        self.right_pane = tk.Frame(main_container, bg=pane_bg, width=300)
        self.right_pane.pack(side="right", fill="y")
        self.right_pane.pack_propagate(False)

        self.actions_card = tk.Frame(self.right_pane, bg=card_bg, bd=0,
                                     highlightthickness=1, highlightbackground=border)
        self.actions_card.pack(side="top", fill="both", expand=True, padx=16, pady=16)

        rows_container = tk.Frame(self.actions_card, bg=card_bg)
        rows_container.pack(side="top", fill="both", expand=True, padx=12, pady=8)

        tk.Label(self.actions_card, text="AKTIONEN", bg=card_bg, fg=muted,
                 font=("Segoe UI", 9, "bold")).pack(side="top", anchor="w", padx=12, pady=(10,2))
        ttk.Separator(self.actions_card, orient="horizontal").pack(fill="x", padx=12, pady=(2,6))

        self._active_tool = tk.StringVar(value="")

        def _vis_clear():
            for r in (self.row_stamp, self.row_write, self.row_esign, self.row_redact, self.row_share):
                r.set_active(False)

        def _set_active(name):
            _vis_clear()
            self._active_tool.set(name or "")
            m = {"stamp": self.row_stamp, "write": self.row_write,
                 "esign": self.row_esign, "redact": self.row_redact}
            if name in m:
                m[name].set_active(True)

        def on_stamp():
            if self._active_tool.get() == "stamp":
                self._set_active("")
                self.deactivate_current_tool()
            else:
                self.deactivate_current_tool()
                self._set_active("stamp")
                self.action_stamp()

        def on_write():
            if self._active_tool.get() == "write":
                self._set_active("")
                self.deactivate_current_tool()
            else:
                self.deactivate_current_tool()
                self._set_active("write")
                self.action_write()

        def on_esign():
            if self._active_tool.get() == "esign":
                self._set_active("")
                self.deactivate_current_tool()
            else:
                self.deactivate_current_tool()
                self._set_active("esign")
                self.action_esignature()

        def on_redact():
            if self._active_tool.get() == "redact":
                self._set_active("")
                self.deactivate_current_tool()
            else:
                self.deactivate_current_tool()
                self._set_active("redact")
                self.action_redact()

        def on_share():
            _set_active("")
            self.action_share_save()

        def sep(parent):
            ttk.Separator(parent, orient="horizontal").pack(fill="x", padx=12, pady=(6,6))

        self.row_stamp  = ActionRow(rows_container, "Stempel", icon="🏷️", accent=accent, command=on_stamp)
        self.row_write  = ActionRow(rows_container, "Schreiben", icon="[T]", accent=accent, command=on_write)
        self.row_esign  = ActionRow(rows_container, "eSignatur", icon="✒️", accent=accent, command=on_esign)
        self.row_redact = ActionRow(rows_container, "Schwärzen", icon="■", accent="#EF4444", command=on_redact)
        self.row_share  = ActionRow(rows_container, "Teilen/Speichern", icon="📤", accent=accent, command=on_share)

        for i, row in enumerate((self.row_stamp, self.row_write, self.row_esign, self.row_redact, self.row_share)):
            row.pack(fill="x", padx=8, pady=(4 if i else 0, 4))
            if i < 4:
                sep(rows_container)

        self.row_write._icon.configure(fg=accent)
        self.row_redact._icon.configure(fg="#EF4444")

        tk.Frame(rows_container, bg=card_bg).pack(fill="both", expand=True)

        # STATUS
        status_bg = _c(self.colors, "pane_bg", "#0F172A")
        muted = _c(self.colors, "muted", "#94A3B8")

        self.status = tk.Frame(self.root, bg=status_bg, height=32)
        self.status.pack(side="bottom", fill="x")

        self.lbl_info = tk.Label(self.status, text="", bg=status_bg, fg=muted, font=("Segoe UI", 9))
        self.lbl_info.pack(side="left", padx=12)

        # SHORTCUTS - nur wenn NICHT in Entry
        def _bind_shortcuts():
            def on_key(key_func):
                def handler(e):
                    if not isinstance(e.widget, tk.Entry):
                        key_func()
                return handler

            self.root.bind_all("<KeyPress-s>", on_key(on_stamp))
            self.root.bind_all("<KeyPress-w>", on_key(on_write))
            self.root.bind_all("<KeyPress-e>", on_key(on_esign))
            self.root.bind_all("<KeyPress-r>", on_key(on_redact))
            self.root.bind_all("<KeyPress-t>", on_key(on_share))

            def _esc(_):
                _set_active("")
                self.deactivate_current_tool()
            self.root.bind_all("<Escape>", _esc)

        _bind_shortcuts()

        self._set_active = _set_active
        self._vis_clear = _vis_clear
        self._redact_overlay = None

    # === KOORDINATEN-UMRECHNUNG (VEREINFACHT) ===
    def _canvas_to_pdf_point(self, page_idx, canvas_x, canvas_y):
        """
        EINFACHE Umrechnung: Canvas-Pixel zu PDF-Punkten
        Verwendet die tatsächliche angezeigte Bildgröße, nicht die Canvas-Größe!
        """
        page = self.pdf_document[page_idx]
        pdf_width = page.rect.width
        pdf_height = page.rect.height
        
        # Hole die aktuelle Display-Information
        if not hasattr(self, '_page_photo'):
            return (canvas_x, pdf_height - canvas_y)  # Fallback
            
        # Die tatsächliche Größe des angezeigten Bildes
        display_width = self._page_photo.width()
        display_height = self._page_photo.height()
        
        if self.fit_to_window:
            # Im Fit-Modus ist das Bild zentriert
            # Finde die Position des Bildes auf dem Canvas
            canvas_width = self.pdf_canvas.winfo_width()
            canvas_height = self.pdf_canvas.winfo_height()
            img_x_offset = (canvas_width - display_width) / 2
            img_y_offset = (canvas_height - display_height) / 2
            
            # Position relativ zum Bild
            rel_x = canvas_x - img_x_offset
            rel_y = canvas_y - img_y_offset
            
            # Außerhalb des Bildes?
            if rel_x < 0 or rel_x > display_width or rel_y < 0 or rel_y > display_height:
                rel_x = max(0, min(display_width, rel_x))
                rel_y = max(0, min(display_height, rel_y))
        else:
            # Im Zoom-Modus startet das Bild bei (0,0)
            rel_x = canvas_x
            rel_y = canvas_y
        
        # Einfache Skalierung: Display-Pixel zu PDF-Punkten
        scale_x = pdf_width / display_width
        scale_y = pdf_height / display_height
        
        pdf_x = rel_x * scale_x
        pdf_y = rel_y * scale_y
        
        # Y-Achse flippen (Canvas: oben=0, PDF: unten=0)
        pdf_y_flipped = pdf_height - pdf_y
        
        return (pdf_x, pdf_y_flipped)

    def _canvas_rect_to_pdf_rect(self, page_idx, x0, y0, x1, y1):
        """Wandelt ein Canvas-Rechteck in ein PDF-Rechteck um"""
        pdf_p0 = self._canvas_to_pdf_point(page_idx, x0, y0)
        pdf_p1 = self._canvas_to_pdf_point(page_idx, x1, y1)
        
        return (
            min(pdf_p0[0], pdf_p1[0]),
            min(pdf_p0[1], pdf_p1[1]),
            max(pdf_p0[0], pdf_p1[0]),
            max(pdf_p0[1], pdf_p1[1])
        )

    # === ACTIONS ===
    def action_stamp(self):
        """Stempel-Tool aktivieren"""
        messagebox.showinfo("Stempel", "Tool aktiviert\n\nTipp: ESC zum Beenden")

    def action_write(self):
        """Schreib-Tool aktivieren"""
        self._text_overlay = {"active": True}
        self._text_drag = None
        self.pdf_canvas.config(cursor="crosshair")
        self.pdf_canvas.bind("<Button-1>", self._text_click, add="+")
        self.pdf_canvas.bind("<B1-Motion>", self._text_drag_move, add="+")
        self.pdf_canvas.bind("<ButtonRelease-1>", self._text_drag_drop, add="+")
        self.pdf_canvas.bind("<Button-3>", self._text_right_click, add="+")  # NEU: Rechtsklick
        self._create_text_panel()
        messagebox.showinfo("Schreiben", 
                          "Text-Tool aktiviert!\n\n"
                          "• Linksklick: Text hinzufügen/auswählen\n"
                          "• Rechtsklick: Text löschen\n"
                          "• ESC: Tool beenden")

    def _create_text_panel(self):
        """Text-Optionen Panel erstellen"""
        if hasattr(self, '_text_panel'):
            return

        card_bg = _c(self.colors, "card_bg", "#111827")
        border = _c(self.colors, "border", "#1E293B")
        muted = _c(self.colors, "muted", "#94A3B8")

        self._text_panel = tk.Frame(self.right_pane, bg=card_bg, bd=0,
                                    highlightthickness=1, highlightbackground=border)
        self._text_panel.pack(side="top", fill="x", padx=16, pady=(16, 8))

        tk.Label(self._text_panel, text="TEXT-OPTIONEN", bg=card_bg, fg=muted,
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=12, pady=(10,2))
        ttk.Separator(self._text_panel, orient="horizontal").pack(fill="x", padx=12, pady=(2,8))

        inner = tk.Frame(self._text_panel, bg=card_bg)
        inner.pack(fill="x", padx=12, pady=(0,12))

        # Schriftart (nur Base-14 sicher exportierbar)
        tk.Label(inner, text="Schriftart:", bg=card_bg, fg=muted,
                 font=("Segoe UI", 9)).grid(row=0, column=0, sticky="w", pady=(0,4))
        self._font_family = tk.StringVar(value=list(self._font_map.keys())[0])
        font_menu = ttk.Combobox(inner, textvariable=self._font_family,
                                 values=list(self._font_map.keys()), state="readonly", width=24)
        font_menu.grid(row=1, column=0, sticky="ew", pady=(0,8))

        # Schriftgröße
        tk.Label(inner, text="Größe:", bg=card_bg, fg=muted,
                 font=("Segoe UI", 9)).grid(row=2, column=0, sticky="w", pady=(0,4))
        self._font_size = tk.IntVar(value=12)
        size_frame = tk.Frame(inner, bg=card_bg)
        size_frame.grid(row=3, column=0, sticky="ew", pady=(0,8))
        tk.Scale(size_frame, from_=8, to=48, orient="horizontal",
                 variable=self._font_size, bg=card_bg, fg=muted,
                 highlightthickness=0, troughcolor="#1E293B").pack(fill="x")

        # Schriftfarbe
        tk.Label(inner, text="Farbe:", bg=card_bg, fg=muted,
                 font=("Segoe UI", 9)).grid(row=4, column=0, sticky="w", pady=(0,4))
        self._text_color = tk.StringVar(value="#000000")
        color_frame = tk.Frame(inner, bg=card_bg)
        color_frame.grid(row=5, column=0, sticky="ew")
        colors = [
            ("#000000", "Schwarz"), ("#FF0000", "Rot"), ("#0000FF", "Blau"),
            ("#00FF00", "Grün"), ("#FFFF00", "Gelb"), ("#FF00FF", "Magenta")
        ]
        for i, (color, name) in enumerate(colors):
            btn = tk.Button(color_frame, bg=color, width=3, height=1,
                            command=lambda c=color: self._text_color.set(c),
                            relief="solid", bd=1)
            btn.grid(row=i//3, column=i%3, padx=2, pady=2)

        inner.columnconfigure(0, weight=1)
        self._bind_panel_traces()

    def _bind_panel_traces(self):
        """Panel-Änderungen an ausgewählten Text binden"""
        def _apply(*_):
            if not getattr(self, "_selected_text", None):
                return
            if getattr(self, "_text_drag", None):
                return
            item, td = self._selected_text
            changed = False
            # Font (Tk-Seite) aus Mapping ableiten
            tk_family = self._font_map.get(self._font_family.get(), ("Helvetica","helv"))[0]
            if td.get("font") != tk_family:
                td["font"] = tk_family
                changed = True
            if td.get("size") != int(self._font_size.get()):
                td["size"] = int(self._font_size.get())
                changed = True
            if td.get("color") != self._text_color.get():
                td["color"] = self._text_color.get()
                changed = True
            if changed:
                self.pdf_canvas.delete(item)
                self._clear_text_selection()
                new_item = self._render_text(td)
                self._selected_text = (new_item, td)
                bbox = self.pdf_canvas.bbox(new_item)
                if bbox:
                    x0, y0, x1, y1 = bbox
                    pad = 3
                    self.pdf_canvas.create_rectangle(
                        x0-pad, y0-pad, x1+pad, y1+pad,
                        outline=_c(self.colors,'accent','#2563EB'),
                        width=1, dash=(3,2),
                        tags=("text_selected",)
                    )
        self._font_family.trace_add("write", _apply)
        self._font_size.trace_add("write", _apply)
        self._text_color.trace_add("write", _apply)

    def _text_click(self, event):
        """Linksklick: Text hinzufügen oder auswählen"""
        if not hasattr(self, '_text_overlay') or not self._text_overlay.get("active"):
            return

        # Klick auf bestehenden Text?
        items = self.pdf_canvas.find_overlapping(event.x-5, event.y-5, event.x+5, event.y+5)
        for item in items:
            if "text_overlay" in self.pdf_canvas.gettags(item):
                td = None
                tags = self.pdf_canvas.gettags(item)
                for tag in tags:
                    if tag.startswith("text_id_"):
                        tid = tag.replace("text_id_", "")
                        if self.current_page in self._texts_by_page:
                            for _td in self._texts_by_page[self.current_page]:
                                if str(id(_td)) == tid:
                                    td = _td
                                    break
                        break
                if not td:
                    return
                try:
                    self._select_text(item, td)
                except:
                    pass
                coords = self.pdf_canvas.coords(item)
                if coords and len(coords) >= 2:
                    x, y = coords[0], coords[1]
                else:
                    x, y = td.get('x', event.x), td.get('y', event.y)
                self._text_drag = {"item": item, "td": td, "dx": event.x - x, "dy": event.y - y}
                return

        # Neuen Text anlegen
        label = self._font_family.get()
        tk_family = self._font_map.get(label, ("Helvetica","helv"))[0]
        text_entry = tk.Entry(
            self.pdf_canvas,
            font=(tk_family, self._font_size.get()),
            fg=self._text_color.get(),
            bg="white",
            insertbackground=self._text_color.get(),
            relief="flat", bd=0
        )
        text_window = self.pdf_canvas.create_window(event.x, event.y, window=text_entry, anchor="nw")
        text_entry.focus_set()

        def save_text(e=None):
            text = text_entry.get()
            if text.strip():
                if self.current_page not in self._texts_by_page:
                    self._texts_by_page[self.current_page] = []
                text_data = {
                    'x': event.x, 'y': event.y, 'text': text,
                    'font': tk_family,
                    'size': self._font_size.get(),
                    'color': self._text_color.get(),
                    'id': id(self._texts_by_page[self.current_page])
                }
                self._texts_by_page[self.current_page].append(text_data)
                self.pdf_canvas.delete(text_window)
                self._render_text(text_data)
            else:
                self.pdf_canvas.delete(text_window)
        text_entry.bind("<Return>", save_text)
        text_entry.bind("<Escape>", lambda e: self.pdf_canvas.delete(text_window))

    def _text_right_click(self, event):
        """NEU: Rechtsklick zum Löschen von Text"""
        if not hasattr(self, '_text_overlay') or not self._text_overlay.get("active"):
            return
        
        # Text unter dem Mauszeiger finden
        items = self.pdf_canvas.find_overlapping(event.x-5, event.y-5, event.x+5, event.y+5)
        for item in items:
            if "text_overlay" in self.pdf_canvas.gettags(item):
                # Text-Daten finden
                td = None
                tags = self.pdf_canvas.gettags(item)
                for tag in tags:
                    if tag.startswith("text_id_"):
                        tid = tag.replace("text_id_", "")
                        if self.current_page in self._texts_by_page:
                            for _td in self._texts_by_page[self.current_page]:
                                if str(id(_td)) == tid:
                                    td = _td
                                    break
                        break
                
                if td:
                    # Text löschen
                    self._delete_text(item, td)
                    self._clear_text_selection()
                return

    def _text_drag_move(self, event):
        """Text verschieben während des Ziehens"""
        d = getattr(self, "_text_drag", None)
        if not d or not d.get("item"):
            return
        item, td = d["item"], d["td"]
        new_x = event.x - d["dx"]
        new_y = event.y - d["dy"]
        self.pdf_canvas.coords(item, new_x, new_y)
        self._clear_text_selection()
        bbox = self.pdf_canvas.bbox(item)
        if bbox:
            x0, y0, x1, y1 = bbox
            pad = 3
            self.pdf_canvas.create_rectangle(
                x0-pad, y0-pad, x1+pad, y1+pad,
                outline=_c(self.colors,'accent','#2563EB'), width=1, dash=(3,2),
                tags=("text_selected",)
            )

    def _text_drag_drop(self, event):
        """Text-Position nach dem Ziehen speichern"""
        d = getattr(self, "_text_drag", None)
        if not d or not d.get("item"):
            return
        item, td = d["item"], d["td"]
        coords = self.pdf_canvas.coords(item)
        if coords and len(coords) >= 2:
            td["x"], td["y"] = coords[0], coords[1]
        self._text_drag = None
        self._clear_text_selection()
        self._selected_text = (item, td)
        bbox = self.pdf_canvas.bbox(item)
        if bbox:
            x0, y0, x1, y1 = bbox
            pad = 3
            self.pdf_canvas.create_rectangle(
                x0-pad, y0-pad, x1+pad, y1+pad,
                outline=_c(self.colors,'accent','#2563EB'),
                width=1, dash=(3,2),
                tags=("text_selected",)
            )

    def _clear_text_selection(self):
        """Text-Auswahl aufheben"""
        for sel in self.pdf_canvas.find_withtag("text_selected"):
            self.pdf_canvas.delete(sel)
        self._selected_text = None

    def _select_text(self, item, text_data):
        """Text auswählen und Panel-Werte setzen"""
        self._clear_text_selection()
        self._selected_text = (item, text_data)
        bbox = self.pdf_canvas.bbox(item)
        if bbox:
            x0,y0,x1,y1 = bbox
            pad = 3
            self.pdf_canvas.create_rectangle(
                x0-pad, y0-pad, x1+pad, y1+pad,
                outline=_c(self.colors,'accent','#2563EB'),
                width=1, dash=(3,2),
                tags=("text_selected",)
            )
        try:
            # Panel mit Eigenschaften füllen (UI-Label setzen)
            for label, (tkfam, _) in self._font_map.items():
                if tkfam.lower() in str(text_data['font']).lower():
                    self._font_family.set(label)
                    break
            self._font_size.set(text_data['size'])
            self._text_color.set(text_data['color'])
        except:
            pass

    def _delete_text(self, item, text_data):
        """Text löschen"""
        if item:
            self.pdf_canvas.delete(item)
        if self.current_page in self._texts_by_page:
            if text_data in self._texts_by_page[self.current_page]:
                self._texts_by_page[self.current_page].remove(text_data)

    def _render_text(self, text_data):
        """Text auf Canvas zeichnen"""
        return self.pdf_canvas.create_text(
            text_data['x'], text_data['y'],
            text=text_data['text'],
            anchor="nw",
            font=(text_data['font'], text_data['size']),
            fill=text_data['color'],
            tags=("text_overlay", f"text_id_{id(text_data)}")
        )

    def _restore_texts(self):
        """Texte der aktuellen Seite wiederherstellen"""
        for item in self.pdf_canvas.find_withtag("text_overlay"):
            self.pdf_canvas.delete(item)
        if self.current_page in self._texts_by_page:
            for text_data in self._texts_by_page[self.current_page]:
                self._render_text(text_data)

    def action_esignature(self):
        """eSignatur-Tool aktivieren"""
        messagebox.showinfo("eSignatur", "Tool aktiviert\n\nTipp: ESC zum Beenden")

    def action_redact(self):
        """Schwärzungs-Tool aktivieren"""
        self._redact_overlay = {"start_x": None, "start_y": None, "current_item": None, "mode": "draw"}
        self.pdf_canvas.config(cursor="crosshair")
        self.pdf_canvas.bind("<Button-1>", self._redact_start, add="+")
        self.pdf_canvas.bind("<B1-Motion>", self._redact_drag, add="+")
        self.pdf_canvas.bind("<ButtonRelease-1>", self._redact_finish, add="+")
        self.pdf_canvas.bind("<Button-3>", self._redact_right_click, add="+")
        self.root.bind("<Up>", lambda e: self._adjust_redact("h", 5))
        self.root.bind("<Down>", lambda e: self._adjust_redact("h", -5))
        self.root.bind("<Right>", lambda e: self._adjust_redact("w", 5))
        self.root.bind("<Left>", lambda e: self._adjust_redact("w", -5))
        self.root.bind("<Delete>", lambda e: self._delete_redact())
        messagebox.showinfo("Schwärzen", "Bereich aufziehen\n\nRechtsklick: Löschen\nESC: Beenden")

    def _redact_start(self, event):
        """Schwärzung starten"""
        if not self._redact_overlay:
            return
        items = self.pdf_canvas.find_overlapping(event.x, event.y, event.x, event.y)
        for item in items:
            if "redact_overlay" in self.pdf_canvas.gettags(item):
                self._redact_overlay["mode"] = "move"
                self._redact_overlay["current_item"] = item
                coords = self.pdf_canvas.coords(item)
                self._redact_overlay["offset"] = (event.x - coords[0], event.y - coords[1])
                return
        self._redact_overlay["mode"] = "draw"
        self._redact_overlay["start_x"] = event.x
        self._redact_overlay["start_y"] = event.y
        self._redact_overlay["current_item"] = self.pdf_canvas.create_rectangle(
            event.x, event.y, event.x, event.y,
            fill="black", outline="red", width=2, tags="redact_overlay"
        )

    def _redact_right_click(self, event):
        """Schwärzung per Rechtsklick löschen"""
        if not self._redact_overlay:
            return
        items = self.pdf_canvas.find_overlapping(event.x, event.y, event.x, event.y)
        for item in items:
            if "redact_overlay" in self.pdf_canvas.gettags(item):
                coords = tuple(self.pdf_canvas.coords(item))
                if self.current_page in self._redactions_by_page:
                    if coords in self._redactions_by_page[self.current_page]:
                        self._redactions_by_page[self.current_page].remove(coords)
                self.pdf_canvas.delete(item)
                if self._redact_overlay.get("current_item") == item:
                    self._redact_overlay["current_item"] = None
                return

    def _redact_drag(self, event):
        """Schwärzung ziehen"""
        if not self._redact_overlay or not self._redact_overlay.get("current_item"):
            return
        if self._redact_overlay["mode"] == "draw":
            x1, y1 = self._redact_overlay["start_x"], self._redact_overlay["start_y"]
            self.pdf_canvas.coords(self._redact_overlay["current_item"],
                                   min(x1, event.x), min(y1, event.y),
                                   max(x1, event.x), max(y1, event.y))
        else:
            ox, oy = self._redact_overlay["offset"]
            coords = self.pdf_canvas.coords(self._redact_overlay["current_item"])    
            w, h = coords[2] - coords[0], coords[3] - coords[1]
            new_x, new_y = event.x - ox, event.y - oy
            self.pdf_canvas.coords(self._redact_overlay["current_item"],
                                   new_x, new_y, new_x + w, new_y + h)

    def _redact_finish(self, event):
        """Schwärzung abschließen"""
        if not self._redact_overlay or self._redact_overlay["mode"] != "draw":
            return
        if self._redact_overlay.get("current_item"):
            coords = self.pdf_canvas.coords(self._redact_overlay["current_item"])
            if abs(coords[2] - coords[0]) < 5 or abs(coords[3] - coords[1]) < 5:
                self.pdf_canvas.delete(self._redact_overlay["current_item"])
                self._redact_overlay["current_item"] = None
            else:
                if self.current_page not in self._redactions_by_page:
                    self._redactions_by_page[self.current_page] = []
                self._redactions_by_page[self.current_page].append(tuple(coords))
        self._redact_overlay["start_x"] = None
        self._redact_overlay["start_y"] = None
        self._redact_overlay["mode"] = "draw"

    def _adjust_redact(self, dim, delta):
        """Schwärzungs-Größe anpassen"""
        if not self._redact_overlay or not self._redact_overlay.get("current_item"):
            return
        coords = self.pdf_canvas.coords(self._redact_overlay["current_item"])
        x1, y1, x2, y2 = coords
        if dim == "h":
            y2 = max(y1 + 5, y2 + delta)
        else:
            x2 = max(x1 + 5, x2 + delta)
        self.pdf_canvas.coords(self._redact_overlay["current_item"], x1, y1, x2, y2)

    def _delete_redact(self):
        """Aktuelle Schwärzung löschen"""
        if self._redact_overlay and self._redact_overlay.get("current_item"):
            coords = tuple(self.pdf_canvas.coords(self._redact_overlay["current_item"]))
            if self.current_page in self._redactions_by_page:
                if coords in self._redactions_by_page[self.current_page]:
                    self._redactions_by_page[self.current_page].remove(coords)
            self.pdf_canvas.delete(self._redact_overlay["current_item"])
            self._redact_overlay["current_item"] = None

    def _restore_redactions(self):
        """Schwärzungen der aktuellen Seite wiederherstellen"""
        for item in self.pdf_canvas.find_withtag("redact_overlay"):
            self.pdf_canvas.delete(item)
        if self.current_page in self._redactions_by_page:
            for coords in self._redactions_by_page[self.current_page]:
                self.pdf_canvas.create_rectangle(
                    *coords, fill="black", outline="red", width=2, tags="redact_overlay"
                )

    # === EXPORT-HILFSFUNKTIONEN ===
    def _hex_to_rgb01(self, hexstr: str):
        """Hex-Farbe zu RGB (0-1) konvertieren"""
        hexstr = hexstr.strip().lstrip('#')
        if len(hexstr) == 3:
            hexstr = ''.join(ch*2 for ch in hexstr)
        r = int(hexstr[0:2], 16) / 255.0
        g = int(hexstr[2:4], 16) / 255.0
        b = int(hexstr[4:6], 16) / 255.0
        return (r, g, b)

    def _fitz_font_from_tk(self, tk_family: str) -> str:
        """Tk-Font zu PyMuPDF Base-14 Font mappen"""
        for label, (tkfam, fitzname) in self._font_map.items():
            if tkfam.lower() in (tk_family or '').lower():
                return fitzname
        name = (tk_family or '').lower()
        if 'time' in name or 'georgia' in name or 'serif' in name:
            return 'times'
        if 'cour' in name or 'mono' in name:
            return 'cour'
        return 'helv'

    def _export_with_overlays(self, target_path):
        """PDF mit allen Overlays exportieren (Schwärzungen und Texte)"""
        src = self.pdf_document
        out = fitz.open()
        out.insert_pdf(src)
        
        for page_idx in range(len(out)):
            page = out[page_idx]
            
            # === SCHWÄRZUNGEN ===
            if page_idx in self._redactions_by_page:
                for (x0, y0, x1, y1) in self._redactions_by_page[page_idx]:
                    # Canvas-Koordinaten zu PDF-Koordinaten
                    rx0, ry0, rx1, ry1 = self._canvas_rect_to_pdf_rect(page_idx, x0, y0, x1, y1)
                    rect = fitz.Rect(rx0, ry0, rx1, ry1)
                    page.draw_rect(rect, color=(0,0,0), fill=(0,0,0))
            
            # === TEXTE ===
            if page_idx in self._texts_by_page:
                for td in self._texts_by_page[page_idx]:
                    # Canvas-Position zu PDF-Position
                    # WICHTIG: Wir müssen die Seite temporär anzeigen, um die korrekte
                    # Bildgröße für die Umrechnung zu haben
                    old_page = self.current_page
                    if page_idx != self.current_page:
                        self.current_page = page_idx
                        self.display_page()
                    
                    pdf_x, pdf_y = self._canvas_to_pdf_point(page_idx, td['x'], td['y'])
                    
                    # Text in PyMuPDF wird an der Baseline eingefügt
                    # Die Y-Position muss angepasst werden
                    font_size = td['size']
                    
                    # PyMuPDF erwartet die Baseline-Position
                    # Da wir von oben-links speichern, müssen wir die Baseline berechnen
                    # Normalerweise ist die Baseline etwa bei 80% der Schrifthöhe von oben
                    pdf_y_baseline = pdf_y + font_size * 0.8
                    
                    # Farbe umrechnen
                    color = self._hex_to_rgb01(td.get('color', '#000000'))
                    
                    # Font-Mapping
                    fontname = self._fitz_font_from_tk(td.get('font', 'Helvetica'))
                    
                    # Text einfügen mit Fehlerbehandlung
                    try:
                        page.insert_text(
                            (pdf_x, pdf_y_baseline),
                            td.get('text', ''),
                            fontsize=font_size,
                            fontname=fontname,
                            color=color
                        )
                    except Exception as e:
                        print(f"Text-Export Fehler: {e}")
                        # Fallback ohne spezielle Font
                        try:
                            page.insert_text(
                                (pdf_x, pdf_y_baseline),
                                td.get('text', ''),
                                fontsize=font_size,
                                color=color
                            )
                        except Exception as e2:
                            print(f"Fallback fehlgeschlagen: {e2}")
                    
                    # Seite zurücksetzen falls geändert
                    if old_page != page_idx:
                        self.current_page = old_page
                        self.display_page()
        
        out.save(target_path)
        out.close()

    def action_share_save(self):
        """Teilen/Speichern Dialog"""
        dlg = tk.Toplevel(self.root)
        dlg.title("Teilen / Speichern")
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.configure(bg=_c(self.colors, "card_bg", "#111827"))
        dlg.resizable(False, False)
        tk.Label(
            dlg, text="Was möchtest du tun?",
            bg=_c(self.colors, "card_bg", "#111827"),
            fg=_c(self.colors, "text_primary", "#ffffff"),
            font=("Segoe UI", 11, "bold")
        ).pack(padx=14, pady=10)

        def do_save():
            from tkinter import filedialog
            initname = os.path.splitext(os.path.basename(self.pdf_path))[0] + "_bearbeitet.pdf"
            path = filedialog.asksaveasfilename(
                parent=dlg, title="Als PDF speichern",
                defaultextension=".pdf",
                filetypes=[("PDF", "*.pdf")],
                initialfile=initname
            )
            if not path:
                return
            try:
                self._export_with_overlays(path)
                messagebox.showinfo("Gespeichert", f"PDF gespeichert:\n{path}", parent=dlg)
                dlg.destroy()
            except Exception as e:
                messagebox.showerror("Fehler beim Speichern", str(e), parent=dlg)

        def do_mail():
            try:
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
                tmp_path = tmp.name
                tmp.close()
                self._export_with_overlays(tmp_path)
                if win32com:
                    try:
                        ol = win32com.client.Dispatch("Outlook.Application")
                        mail = ol.CreateItem(0)
                        mail.Subject = os.path.basename(self.pdf_path) + " – bearbeitet"
                        mail.Body = "Anbei die bearbeitete PDF."
                        mail.Attachments.Add(Source=tmp_path)
                        mail.Display()
                        dlg.destroy()
                        return
                    except Exception:
                        pass
                messagebox.showinfo(
                    "Datei exportiert",
                    "Outlook nicht verfügbar. Die Datei liegt hier:\n" + tmp_path,
                    parent=dlg
                )
                try:
                    os.startfile(os.path.dirname(tmp_path))
                except Exception:
                    webbrowser.open("file://" + os.path.dirname(tmp_path))
                dlg.destroy()
            except Exception as e:
                messagebox.showerror("E-Mail-Export fehlgeschlagen", str(e), parent=dlg)

        ttk.Button(dlg, text="💾 Als PDF speichern…", command=do_save).pack(fill="x", padx=14, pady=(4,6))
        ttk.Button(dlg, text="📧 In E-Mail öffnen…", command=do_mail).pack(fill="x", padx=14, pady=(0,12))

    def deactivate_current_tool(self):
        """Aktuelles Tool deaktivieren"""
        try:
            self.pdf_canvas.config(cursor="")
        except:
            pass
        for seq in ("<Button-1>", "<B1-Motion>", "<ButtonRelease-1>", "<Button-3>"):
            try: self.pdf_canvas.unbind(seq)
            except: pass
        try: self._clear_text_selection()
        except: pass
        for seq in ("<Up>", "<Down>", "<Left>", "<Right>", "<Delete>"):
            try: self.root.unbind(seq)
            except: pass
        if hasattr(self, "_text_overlay"):
            self._text_overlay["active"] = False
        if hasattr(self, "_text_panel"):
            self._text_panel.destroy()
            delattr(self, "_text_panel")
        self._redact_overlay = None

    # === THUMBNAILS ===
    def _on_thumb_canvas_configure(self, event):
        """Thumbnail-Canvas bei Größenänderung anpassen"""
        self.thumb_canvas.configure(scrollregion=self.thumb_canvas.bbox("all"))
        ids = self.thumb_canvas.find_all()
        if ids:
            self.thumb_canvas.itemconfig(ids[0], width=event.width)

    def _build_thumbnail_placeholders(self):
        """Thumbnail-Platzhalter erstellen"""
        self._thumb_frames = []
        for page_num in range(self.total_pages):
            thumb_container = tk.Frame(self.thumb_inner, bg=self.colors['bg_primary'],
                                       highlightthickness=1, highlightbackground="#223041")
            thumb_container.pack(pady=8, fill='x')
            self._thumb_frames.append(thumb_container)

            btn = tk.Button(thumb_container, text=str(page_num + 1),
                             command=lambda p=page_num: self.goto_page(p),
                             relief="solid", bd=1, cursor="hand2",
                             bg=self.colors['button_bg'], fg=self.colors['text_primary'],
                             activebackground=self.colors['button_hover'],
                             font=('Segoe UI', 10), highlightthickness=0, borderwidth=1)
            btn.pack()

            page_label = tk.Label(thumb_container, text=f"Seite {page_num + 1}",
                                  font=('Segoe UI', 9), bg=self.colors['bg_primary'],
                                  fg=self.colors['text_muted'])
            page_label.pack(pady=(8, 0))
            self._thumb_buttons.append(btn)

    def _mark_active_thumb(self, idx):
        """Aktive Thumbnail markieren"""
        accent = _c(self.colors, "accent", "#2563EB")
        border = _c(self.colors, "border", "#1E293B")
        for i, frame in enumerate(self._thumb_frames):
            frame.configure(highlightthickness=(2 if i == idx else 1),
                            highlightbackground=accent if i == idx else border)
        self._scroll_thumb_into_view(idx)

    def _scroll_thumb_into_view(self, idx):
        """Thumbnail in Sichtbereich scrollen"""
        if not (0 <= idx < len(self._thumb_frames)):
            return
        self.thumb_canvas.update_idletasks()
        frame = self._thumb_frames[idx]
        content_h = max(1, self.thumb_inner.winfo_height())
        view_h = max(1, self.thumb_canvas.winfo_height())
        y_top = frame.winfo_y()
        y_bot = y_top + frame.winfo_height()
        y0 = self.thumb_canvas.canvasy(0)
        y1 = y0 + view_h
        if y_top < y0:
            frac = y_top / content_h
            self.thumb_canvas.yview_moveto(max(0.0, min(1.0, frac)))
        elif y_bot > y1:
            target_top = y_bot - view_h
            frac = target_top / content_h
            self.thumb_canvas.yview_moveto(max(0.0, min(1.0, frac)))

    def _schedule_thumb_batch(self):
        """Thumbnails batch-weise laden"""
        if self._thumb_batch_idx >= self.total_pages:
            return
        end = min(self._thumb_batch_idx + self._thumb_batch_size, self.total_pages)
        for i in range(self._thumb_batch_idx, end):
            self._ensure_thumb(i)
        self._thumb_batch_idx = end
        if self._thumb_batch_idx < self.total_pages:
            self.root.after(50, self._schedule_thumb_batch)

    def _ensure_thumb(self, page_index):
        """Einzelne Thumbnail sicherstellen"""
        if page_index in self.thumbnail_cache:
            photo = self.thumbnail_cache[page_index]
            self.thumbnail_cache.move_to_end(page_index)
        else:
            page = self.pdf_document[page_index]
            mat = fitz.Matrix(0.5, 0.5)
            pix = page.get_pixmap(matrix=mat)
            img_data = pix.tobytes("png")
            img = Image.open(io.BytesIO(img_data))
            img.thumbnail(self._thumb_target_size, Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            self.thumbnail_cache[page_index] = photo
            while len(self.thumbnail_cache) > self.max_thumb_cache:
                self.thumbnail_cache.popitem(last=False)

        btn = self._thumb_buttons[page_index]
        btn.config(image=photo, text="", compound='none')
        self._thumb_photos_by_button[btn] = photo

    # === PDF DISPLAY ===
    def display_page(self):
        """Aktuelle Seite anzeigen"""
        page = self.pdf_document[self.current_page]
        cw = self.pdf_canvas.winfo_width()
        ch = self.pdf_canvas.winfo_height()

        if cw < 50 or ch < 50:
            self.root.after(50, self.display_page)
            return

        canvas_width = max(50, cw)
        canvas_height = max(50, ch)

        if self.fit_to_window:
            mat = fitz.Matrix(self.base_zoom, self.base_zoom)
            pix = page.get_pixmap(matrix=mat)
            img_data = pix.tobytes("png")
            img = Image.open(io.BytesIO(img_data))
            target_w = max(1, canvas_width - 40)
            target_h = max(1, canvas_height - 40)
            img.thumbnail((target_w, target_h), Image.Resampling.LANCZOS)
            self._page_photo = ImageTk.PhotoImage(img)

            self.pdf_canvas.delete("pdf")
            self.pdf_canvas.create_image(
                canvas_width // 2, canvas_height // 2,
                image=self._page_photo, anchor=tk.CENTER, tags="pdf"
            )
            self.pdf_canvas.configure(scrollregion=(0, 0, canvas_width, canvas_height))
            self.v_scroll.grid_remove()
            self.h_scroll.grid_remove()
        else:
            mat = fitz.Matrix(self.zoom, self.zoom)
            pix = page.get_pixmap(matrix=mat)
            img_data = pix.tobytes("png")
            img = Image.open(io.BytesIO(img_data))
            self._page_photo = ImageTk.PhotoImage(img)

            self.pdf_canvas.delete("pdf")
            self.pdf_canvas.create_image(0, 0, image=self._page_photo, anchor=tk.NW, tags="pdf")
            self.pdf_canvas.configure(scrollregion=(0, 0, img.width, img.height))
            self.v_scroll.grid()
            self.h_scroll.grid()

        try:
            self.lbl_info.config(text=f"Seite {self.current_page + 1}/{self.total_pages}")
        except:
            pass

        self._mark_active_thumb(self.current_page)
        self._restore_redactions()
        self._restore_texts()

    # === NAVIGATION ===
    def goto_page(self, page_num):
        """Zu Seite springen"""
        if 0 <= page_num < self.total_pages:
            self.current_page = page_num
            self._ensure_thumb(page_num)
            self.display_page()
            self._scroll_thumb_into_view(self.current_page)

    def next_page(self):
        """Nächste Seite"""
        if self.current_page < self.total_pages - 1:
            self.goto_page(self.current_page + 1)

    def prev_page(self):
        """Vorherige Seite"""
        if self.current_page > 0:
            self.goto_page(self.current_page - 1)

    def toggle_fit(self):
        """Zwischen Fit-to-Window und Zoom-Modus wechseln"""
        self.fit_to_window = not self.fit_to_window
        self.display_page()

    def zoom_in(self, step=0.1):
        """Hineinzoomen"""
        self.fit_to_window = False
        self.zoom = min(self.max_zoom, self.zoom + step)
        self.display_page()

    def zoom_out(self, step=0.1):
        """Herauszoomen"""
        self.fit_to_window = False
        self.zoom = max(self.min_zoom, self.zoom - step)
        self.display_page()

    def zoom_reset(self):
        """Zoom zurücksetzen"""
        self.fit_to_window = False
        self.zoom = 1.0
        self.display_page()

    # === EVENTS ===
    def bind_events(self):
        """Event-Bindings einrichten"""
        try:
            self.root.bind('<Right>', lambda e: self.next_page())
            self.root.bind('<Left>',  lambda e: self.prev_page())
            self.root.bind('<Escape>', lambda e: self.close_viewer())
            self.root.protocol("WM_DELETE_WINDOW", self.close_viewer)
        except:
            pass

        self.pdf_canvas.bind('<Configure>',
                            lambda e: self.display_page() if self.fit_to_window else None)

        system = platform.system()
        if system == "Windows":
            self.pdf_canvas.bind("<MouseWheel>", self._on_mouse_wheel_windows)
            self.thumb_canvas.bind("<MouseWheel>", self._on_thumb_wheel_windows)
        elif system == "Darwin":
            self.pdf_canvas.bind("<MouseWheel>", self._on_mouse_wheel_macos)
            self.thumb_canvas.bind("<MouseWheel>", self._on_thumb_wheel_macos)
        else:
            self.pdf_canvas.bind("<Button-4>", lambda e: self._on_mouse_wheel_linux(1, e))
            self.pdf_canvas.bind("<Button-5>", lambda e: self._on_mouse_wheel_linux(-1, e))
            self.thumb_canvas.bind("<Button-4>", lambda e: self._on_thumb_wheel_linux(1, e))
            self.thumb_canvas.bind("<Button-5>", lambda e: self._on_thumb_wheel_linux(-1, e))

    def _wheel_to_pages(self, direction):
        """Mausrad zu Seitenwechsel"""
        if direction > 0:
            self.prev_page()
        else:
            self.next_page()

    def _on_mouse_wheel_windows(self, event):
        """Mausrad Windows"""
        ctrl = (event.state & 0x0004) != 0
        if ctrl:
            self.zoom_in(0.15) if event.delta > 0 else self.zoom_out(0.15)
        else:
            self._wheel_to_pages(1 if event.delta > 0 else -1)

    def _on_mouse_wheel_macos(self, event):
        """Mausrad macOS"""
        ctrl = (event.state & 0x0004) != 0
        if ctrl:
            self.zoom_in(0.1) if event.delta > 0 else self.zoom_out(0.1)
        else:
            self._wheel_to_pages(1 if event.delta > 0 else -1)

    def _on_mouse_wheel_linux(self, direction, event):
        """Mausrad Linux"""
        self._wheel_to_pages(direction)

    def _on_thumb_wheel_windows(self, event):
        """Thumbnail-Scrollen Windows"""
        self.thumb_canvas.yview_scroll(-1 * (event.delta // 120), "units")

    def _on_thumb_wheel_macos(self, event):
        """Thumbnail-Scrollen macOS"""
        self.thumb_canvas.yview_scroll(-1 * (1 if event.delta > 0 else -1), "units")

    def _on_thumb_wheel_linux(self, direction, event):
        """Thumbnail-Scrollen Linux"""
        self.thumb_canvas.yview_scroll(-1 * direction, "units")

    def close_viewer(self):
        """Viewer schließen"""
        try:
            if self.pdf_document:
                self.pdf_document.close()
        finally:
            self.root.quit()
            self.root.destroy()


# === STANDALONE START ===
if __name__ == "__main__":
    import tkinter as tk
    from tkinter import filedialog

    def run_viewer(pdf_path: str):
        root = tk.Tk()
        class MockSettings:
            pass
        ModernPDFViewer(root, MockSettings(), pdf_path)
        root.mainloop()

    # 1) Pfad per Argument?
    if len(sys.argv) > 1:
        pdf_path = sys.argv[1]
        if os.path.exists(pdf_path):
            run_viewer(pdf_path)
        else:
            print(f"Datei nicht gefunden: {pdf_path}")
    else:
        # 2) Sonst: Dialog anzeigen
        picker = tk.Tk()
        picker.withdraw()
        pdf_path = filedialog.askopenfilename(
            title="PDF-Datei auswählen",
            filetypes=[("PDF files", "*.pdf"), ("Alle Dateien", "*.*")]
        )
        picker.destroy()

        if pdf_path:
            run_viewer(pdf_path)