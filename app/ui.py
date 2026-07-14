from __future__ import annotations

from io import BytesIO
from pathlib import Path
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk

from PIL import Image, ImageOps, ImageTk

from app.editor import CutoutEditor
from app.file_service import build_default_output_path, ensure_supported_image
from app.remover import remove_background


APP_TITLE = "PNG Factory — 精修工作台"
WINDOW_SIZE = "1180x760"
BG = "#101417"
PANEL = "#181e22"
PANEL_ALT = "#20272c"
TEXT = "#edf3f5"
MUTED = "#93a1a8"
ACCENT = "#4de3a3"
ACCENT_DARK = "#173d31"
DANGER = "#ff6b6b"
CARD_BORDER = "#2a343a"
CANVAS_BG = "#242b2f"

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("green")


class PngFactoryApp:
    def __init__(self, root: ctk.CTk) -> None:
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry(WINDOW_SIZE)
        self.root.minsize(960, 640)
        self.root.configure(fg_color=BG)

        self.selected_file = tk.StringVar()
        self.status_text = tk.StringVar(value="選擇圖片，開始建立透明背景。")
        self.brush_mode = tk.StringVar(value="erase")
        self.brush_size = tk.IntVar(value=36)
        self.brush_hardness = tk.IntVar(value=72)
        self.editor: CutoutEditor | None = None
        self.preview_photo: ImageTk.PhotoImage | None = None
        self.preview_scale = 1.0
        self.preview_offset = (0, 0)
        self.zoom_factor = 1.0
        self.pan_offset = [0, 0]
        self.pan_start: tuple[int, int] | None = None
        self.last_paint_point: tuple[float, float] | None = None
        self.is_processing = False
        self.has_auto_cutout = False

        self._build_layout()
        self.root.bind("<Control-z>", lambda _event: self.undo())
        self.root.bind("<Control-s>", lambda _event: self.save_image())

    def _build_layout(self) -> None:
        header = ctk.CTkFrame(self.root, fg_color="transparent", height=72)
        header.pack(fill="x", padx=24, pady=(14, 10))
        header.pack_propagate(False)
        ctk.CTkLabel(
            header,
            text="PNG / FACTORY",
            text_color=TEXT,
            font=ctk.CTkFont(family="Segoe UI", size=22, weight="bold"),
        ).pack(side="left", pady=10)
        ctk.CTkLabel(
            header,
            text="CUTOUT LAB",
            text_color=ACCENT,
            fg_color=ACCENT_DARK,
            corner_radius=8,
            width=104,
            height=28,
            font=ctk.CTkFont(family="Consolas", size=11, weight="bold"),
        ).pack(side="left", padx=(18, 0), pady=17)
        ctk.CTkLabel(
            header,
            text="遮罩精修工作台",
            text_color=MUTED,
            font=ctk.CTkFont(family="Microsoft JhengHei UI", size=12),
        ).pack(side="left", padx=(12, 0), pady=18)

        workspace = ctk.CTkFrame(self.root, fg_color="transparent")
        workspace.pack(fill="both", expand=True, padx=20, pady=(0, 14))
        workspace.grid_columnconfigure(1, weight=1)
        workspace.grid_rowconfigure(0, weight=1)

        self._build_left_panel(workspace)
        self._build_canvas(workspace)
        self._build_right_panel(workspace)

        footer = ctk.CTkFrame(self.root, fg_color=PANEL, corner_radius=0, height=38)
        footer.pack(fill="x")
        footer.pack_propagate(False)
        ctk.CTkLabel(footer, textvariable=self.status_text, text_color=MUTED, font=("Microsoft JhengHei UI", 11)).pack(side="left", padx=22)
        ctk.CTkLabel(footer, text="CTRL + Z  復原     CTRL + S  儲存", text_color="#647279", font=("Consolas", 10)).pack(side="right", padx=22)

    def _build_left_panel(self, parent: ctk.CTkFrame) -> None:
        panel = ctk.CTkFrame(parent, width=224, corner_radius=16, fg_color=PANEL, border_width=1, border_color=CARD_BORDER)
        panel.grid(row=0, column=0, sticky="ns", padx=(0, 12))
        panel.grid_propagate(False)
        content = ctk.CTkFrame(panel, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=18, pady=20)

        self._section_label(content, "01", "來源圖片", "JPG · JPEG · PNG")
        ctk.CTkButton(content, text="＋  選擇圖片", command=self.choose_file, height=42, corner_radius=10, fg_color=ACCENT, hover_color="#70ecb7", text_color="#08140f", font=("Microsoft JhengHei UI", 13, "bold")).pack(fill="x", pady=(12, 0))
        self.file_label = ctk.CTkLabel(content, text="尚未選擇檔案", text_color=MUTED, anchor="w", justify="left", wraplength=178, font=("Microsoft JhengHei UI", 11))
        self.file_label.pack(fill="x", pady=(10, 22))

        self._divider(content)
        self._section_label(content, "02", "自動去背", "建立初始透明遮罩")
        self.process_button = ctk.CTkButton(content, text="執行去背", command=self.process_image, height=40, corner_radius=10, fg_color=PANEL_ALT, hover_color="#303a40", border_width=1, border_color="#354148", font=("Microsoft JhengHei UI", 12, "bold"))
        self.process_button.pack(fill="x", pady=(12, 0))

        ctk.CTkFrame(content, fg_color="transparent").pack(fill="both", expand=True)
        self._divider(content)
        self._section_label(content, "03", "輸出檔案", "透明 PNG")
        self.save_button = ctk.CTkButton(content, text="儲存透明 PNG", command=self.save_image, state="disabled", height=42, corner_radius=10, fg_color=ACCENT, hover_color="#70ecb7", text_color="#08140f", font=("Microsoft JhengHei UI", 13, "bold"))
        self.save_button.pack(fill="x", pady=(12, 0))

    def _section_label(self, parent: ctk.CTkFrame, number: str, title: str, subtitle: str) -> None:
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x")
        ctk.CTkLabel(row, text=number, width=30, height=28, corner_radius=7, fg_color=ACCENT_DARK, text_color=ACCENT, font=("Consolas", 11, "bold")).pack(side="left")
        copy = ctk.CTkFrame(row, fg_color="transparent")
        copy.pack(side="left", padx=(10, 0))
        ctk.CTkLabel(copy, text=title, text_color=TEXT, anchor="w", font=("Microsoft JhengHei UI", 12, "bold")).pack(anchor="w")
        ctk.CTkLabel(copy, text=subtitle, text_color=MUTED, anchor="w", font=("Microsoft JhengHei UI", 10)).pack(anchor="w")

    def _divider(self, parent: ctk.CTkFrame) -> None:
        ctk.CTkFrame(parent, height=1, fg_color=CARD_BORDER).pack(fill="x", pady=(0, 22))

    def _build_canvas(self, parent: ctk.CTkFrame) -> None:
        canvas_frame = ctk.CTkFrame(parent, corner_radius=16, fg_color=PANEL_ALT, border_width=1, border_color=CARD_BORDER)
        canvas_frame.grid(row=0, column=1, sticky="nsew")
        self.canvas = tk.Canvas(canvas_frame, bg=CANVAS_BG, highlightthickness=0, cursor="crosshair", bd=0)
        self.canvas.pack(fill="both", expand=True, padx=7, pady=7)
        self.canvas.bind("<Configure>", lambda _event: self._draw_preview())
        self.canvas.bind("<ButtonPress-1>", self._start_stroke)
        self.canvas.bind("<B1-Motion>", self._continue_stroke)
        self.canvas.bind("<ButtonRelease-1>", self._end_stroke)
        self.canvas.bind("<Motion>", self._show_brush_cursor)
        self.canvas.bind("<Leave>", lambda _event: self.canvas.delete("brush_cursor"))
        self.canvas.bind("<MouseWheel>", self._mouse_zoom)
        self.canvas.bind("<Button-4>", lambda _event: self._change_zoom(1.15))
        self.canvas.bind("<Button-5>", lambda _event: self._change_zoom(1 / 1.15))
        self.canvas.bind("<ButtonPress-2>", self._start_pan)
        self.canvas.bind("<B2-Motion>", self._continue_pan)
        self.canvas.bind("<ButtonRelease-2>", self._end_pan)
        self.canvas.bind("<ButtonPress-3>", self._start_pan)
        self.canvas.bind("<B3-Motion>", self._continue_pan)
        self.canvas.bind("<ButtonRelease-3>", self._end_pan)
        self._draw_empty_canvas()

    def _build_right_panel(self, parent: ctk.CTkFrame) -> None:
        panel = ctk.CTkScrollableFrame(parent, width=234, corner_radius=16, fg_color=PANEL, border_width=1, border_color=CARD_BORDER, scrollbar_button_color="#354148", scrollbar_button_hover_color="#46555d")
        panel.grid(row=0, column=2, sticky="ns", padx=(12, 0))
        ctk.CTkLabel(panel, text="精修工具", text_color=TEXT, anchor="w", font=("Microsoft JhengHei UI", 16, "bold")).pack(fill="x", padx=4)
        ctk.CTkLabel(panel, text="標記邊緣，讓模型理解你的需求", text_color=MUTED, anchor="w", font=("Microsoft JhengHei UI", 10)).pack(fill="x", padx=4, pady=(1, 15))

        mode_card = ctk.CTkFrame(panel, fg_color=PANEL_ALT, corner_radius=12)
        mode_card.pack(fill="x", padx=4, pady=(0, 18))
        ctk.CTkRadioButton(mode_card, text="擦除背景", variable=self.brush_mode, value="erase", fg_color=DANGER, hover_color="#ff8787", border_color="#58656b", text_color=TEXT, font=("Microsoft JhengHei UI", 12, "bold")).pack(fill="x", padx=14, pady=(13, 8))
        ctk.CTkRadioButton(mode_card, text="還原主體", variable=self.brush_mode, value="restore", fg_color=ACCENT, hover_color="#70ecb7", border_color="#58656b", text_color=TEXT, font=("Microsoft JhengHei UI", 12, "bold")).pack(fill="x", padx=14, pady=(8, 13))

        size_row = ctk.CTkFrame(panel, fg_color="transparent")
        size_row.pack(fill="x")
        ctk.CTkLabel(size_row, text="筆刷大小", text_color=TEXT, font=("Microsoft JhengHei UI", 11, "bold")).pack(side="left")
        self.size_label = ctk.CTkLabel(size_row, text="36 px", text_color=ACCENT, fg_color=ACCENT_DARK, corner_radius=6, width=52, height=24, font=("Consolas", 10, "bold"))
        self.size_label.pack(side="right")
        ctk.CTkSlider(panel, from_=2, to=160, variable=self.brush_size, command=self._update_brush_label, button_color=ACCENT, button_hover_color="#70ecb7", progress_color=ACCENT_DARK, fg_color="#303a40", height=18).pack(fill="x", pady=(8, 16))

        hardness_row = ctk.CTkFrame(panel, fg_color="transparent")
        hardness_row.pack(fill="x")
        ctk.CTkLabel(hardness_row, text="筆刷硬度", text_color=TEXT, font=("Microsoft JhengHei UI", 11, "bold")).pack(side="left")
        self.hardness_label = ctk.CTkLabel(hardness_row, text="72%", text_color=ACCENT, fg_color=ACCENT_DARK, corner_radius=6, width=52, height=24, font=("Consolas", 10, "bold"))
        self.hardness_label.pack(side="right")
        ctk.CTkSlider(panel, from_=10, to=100, variable=self.brush_hardness, command=self._update_hardness_label, button_color=ACCENT, button_hover_color="#70ecb7", progress_color=ACCENT_DARK, fg_color="#303a40", height=18).pack(fill="x", pady=(8, 20))

        zoom_row = ctk.CTkFrame(panel, fg_color=PANEL_ALT, corner_radius=10)
        zoom_row.pack(fill="x", pady=(0, 14))
        ctk.CTkButton(zoom_row, text="−", width=38, height=34, corner_radius=8, fg_color="transparent", hover_color="#354148", command=lambda: self._change_zoom(1 / 1.25), font=("Segoe UI", 18)).pack(side="left", padx=3, pady=3)
        self.zoom_label = ctk.CTkLabel(zoom_row, text="適合畫面", text_color=MUTED, anchor="center", font=("Consolas", 10))
        self.zoom_label.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(zoom_row, text="＋", width=38, height=34, corner_radius=8, fg_color="transparent", hover_color="#354148", command=lambda: self._change_zoom(1.25), font=("Segoe UI", 18)).pack(side="right", padx=3, pady=3)

        secondary = {"height": 36, "corner_radius": 9, "fg_color": PANEL_ALT, "hover_color": "#303a40", "border_width": 1, "border_color": "#354148", "font": ("Microsoft JhengHei UI", 11)}
        ctk.CTkButton(panel, text="適合畫面", command=self.fit_to_canvas, **secondary).pack(fill="x", pady=(0, 7))
        ctk.CTkButton(panel, text="↶  復原上一步", command=self.undo, **secondary).pack(fill="x", pady=(0, 7))
        ctk.CTkButton(panel, text="重設自動遮罩", command=self.reset_mask, **secondary).pack(fill="x")
        self.refine_button = ctk.CTkButton(
            panel,
            text="✦  智慧精修",
            command=self.smart_refine,
            state="disabled",
            height=42,
            corner_radius=10,
            fg_color=ACCENT,
            hover_color="#70ecb7",
            text_color="#08140f",
            font=("Microsoft JhengHei UI", 13, "bold"),
        )
        self.refine_button.pack(fill="x", pady=(12, 0))

        tip = ctk.CTkFrame(panel, fg_color="#141a1d", corner_radius=10, border_width=1, border_color=CARD_BORDER)
        tip.pack(fill="x", pady=(18, 4))
        ctk.CTkLabel(tip, text="PRO TIP", text_color=ACCENT, font=("Consolas", 10, "bold")).pack(anchor="w", padx=12, pady=(10, 2))
        ctk.CTkLabel(tip, text="滾輪縮放；按住中鍵或右鍵移動畫布。柔邊筆刷適合頭髮與商品邊緣。", text_color=MUTED, wraplength=188, justify="left", font=("Microsoft JhengHei UI", 10)).pack(anchor="w", padx=12, pady=(0, 11))

    def choose_file(self) -> None:
        file_path = filedialog.askopenfilename(title="選擇圖片", filetypes=[("Image Files", "*.jpg *.jpeg *.png")])
        if not file_path:
            return
        try:
            input_path = ensure_supported_image(file_path)
            with Image.open(input_path) as opened_image:
                source = ImageOps.exif_transpose(opened_image).convert("RGBA")
            self.editor = CutoutEditor(source, source.copy())
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"無法載入圖片：\n{exc}")
            return

        self.selected_file.set(file_path)
        self.file_label.configure(text=Path(file_path).name, text_color=TEXT)
        self.status_text.set("圖片已載入，點擊「執行去背」。")
        self.save_button.configure(state="disabled")
        self.refine_button.configure(state="disabled")
        self.has_auto_cutout = False
        self.zoom_factor = 1.0
        self.pan_offset = [0, 0]
        self._draw_preview()

    def process_image(self) -> None:
        if self.is_processing:
            return
        raw_path = self.selected_file.get().strip()
        if not raw_path:
            messagebox.showwarning(APP_TITLE, "請先選擇圖片。")
            return
        try:
            input_path = ensure_supported_image(raw_path)
            if not input_path.is_file():
                raise FileNotFoundError("找不到選擇的圖片檔案。")
            with Image.open(input_path) as opened_image:
                normalized_image = ImageOps.exif_transpose(opened_image).convert("RGBA")
            input_buffer = BytesIO()
            normalized_image.save(input_buffer, format="PNG")
            input_bytes = input_buffer.getvalue()
        except Exception as exc:
            messagebox.showerror(APP_TITLE, str(exc))
            return

        self.is_processing = True
        self.process_button.configure(state="disabled", text="處理中…")
        self.status_text.set("AI 正在建立遮罩，請稍候…")
        threading.Thread(target=self._process_worker, args=(input_bytes,), daemon=True).start()

    def _process_worker(self, input_bytes: bytes) -> None:
        try:
            output_bytes = remove_background(input_bytes)
            source = Image.open(BytesIO(input_bytes)).convert("RGBA")
            cutout = Image.open(BytesIO(output_bytes)).convert("RGBA")
            editor = CutoutEditor(source, cutout)
        except Exception as exc:
            self.root.after(0, lambda error=exc: self._finish_processing(None, error))
        else:
            self.root.after(0, self._finish_processing, editor, None)

    def _finish_processing(self, editor: CutoutEditor | None, error: Exception | None) -> None:
        self.is_processing = False
        self.process_button.configure(state="normal", text="重新執行去背")
        if error is not None:
            self.status_text.set("去背失敗。")
            messagebox.showerror(APP_TITLE, str(error))
            return
        self.editor = editor
        self.has_auto_cutout = True
        self.save_button.configure(state="normal")
        self.refine_button.configure(state="normal")
        self.status_text.set("去背完成。使用右側筆刷精修透明遮罩。")
        self._draw_preview()

    def _draw_empty_canvas(self, text: str = "透明畫布") -> None:
        self.canvas.delete("all")
        width = max(self.canvas.winfo_width(), 400)
        height = max(self.canvas.winfo_height(), 400)
        self.canvas.create_text(width / 2, height / 2 - 8, text=text, fill="#718087", font=("Segoe UI Semibold", 15))
        self.canvas.create_text(width / 2, height / 2 + 20, text="選擇圖片後，預覽會顯示在這裡", fill="#4f5c62", font=("Segoe UI", 10))

    def _draw_preview(self) -> None:
        if self.editor is None:
            return
        self.canvas.delete("all")
        canvas_w = max(self.canvas.winfo_width(), 1)
        canvas_h = max(self.canvas.winfo_height(), 1)
        image = self.editor.render()
        image_w, image_h = image.size
        fit_scale = min((canvas_w - 54) / image_w, (canvas_h - 54) / image_h, 1.0)
        self.preview_scale = fit_scale * self.zoom_factor
        display_size = (max(1, int(image_w * self.preview_scale)), max(1, int(image_h * self.preview_scale)))
        preview = image.resize(display_size, Image.Resampling.LANCZOS)
        self.preview_offset = (
            (canvas_w - display_size[0]) // 2 + self.pan_offset[0],
            (canvas_h - display_size[1]) // 2 + self.pan_offset[1],
        )
        self._draw_checkerboard(*self.preview_offset, *display_size)
        self.preview_photo = ImageTk.PhotoImage(preview)
        self.canvas.create_image(*self.preview_offset, anchor="nw", image=self.preview_photo, tags="preview")

    def _draw_checkerboard(self, x: int, y: int, width: int, height: int) -> None:
        tile = 14
        colors = ("#d9dfe1", "#bfc8cb")
        for row, yy in enumerate(range(y, y + height, tile)):
            for col, xx in enumerate(range(x, x + width, tile)):
                self.canvas.create_rectangle(xx, yy, min(xx + tile, x + width), min(yy + tile, y + height), fill=colors[(row + col) % 2], outline="")

    def _canvas_to_image(self, event: tk.Event) -> tuple[float, float] | None:
        if self.editor is None:
            return None
        x = (event.x - self.preview_offset[0]) / self.preview_scale
        y = (event.y - self.preview_offset[1]) / self.preview_scale
        width, height = self.editor.size
        if 0 <= x < width and 0 <= y < height:
            return x, y
        return None

    def _start_stroke(self, event: tk.Event) -> None:
        point = self._canvas_to_image(event)
        if point is None or self.editor is None:
            return
        self.editor.begin_stroke()
        self.last_paint_point = point
        self._paint_segment(point, point)

    def _continue_stroke(self, event: tk.Event) -> None:
        point = self._canvas_to_image(event)
        if point is None or self.last_paint_point is None:
            return
        self._paint_segment(self.last_paint_point, point)
        self.last_paint_point = point

    def _end_stroke(self, _event: tk.Event) -> None:
        self.last_paint_point = None
        if self.editor is not None:
            self._draw_preview()
            self.status_text.set("遮罩已修改，記得儲存輸出。")

    def _paint_segment(self, start: tuple[float, float], end: tuple[float, float]) -> None:
        if self.editor is None:
            return
        radius = self.brush_size.get() / 2
        distance = max(abs(end[0] - start[0]), abs(end[1] - start[1]))
        steps = max(1, int(distance / max(radius * 0.35, 1)))
        for index in range(steps + 1):
            ratio = index / steps
            x = start[0] + (end[0] - start[0]) * ratio
            y = start[1] + (end[1] - start[1]) * ratio
            self.editor.paint(
                x,
                y,
                radius,
                self.brush_mode.get(),
                self.brush_hardness.get() / 100,
            )
        self._draw_preview()

    def _update_brush_label(self, value: str) -> None:
        self.size_label.configure(text=f"{int(float(value))} px")

    def _update_hardness_label(self, value: str) -> None:
        self.hardness_label.configure(text=f"{int(float(value))}%")

    def _show_brush_cursor(self, event: tk.Event) -> None:
        self.canvas.delete("brush_cursor")
        if self._canvas_to_image(event) is None:
            return
        radius = max(2, self.brush_size.get() * self.preview_scale / 2)
        color = DANGER if self.brush_mode.get() == "erase" else ACCENT
        self.canvas.create_oval(
            event.x - radius,
            event.y - radius,
            event.x + radius,
            event.y + radius,
            outline=color,
            width=2,
            tags="brush_cursor",
        )
        self.canvas.create_oval(
            event.x - 1,
            event.y - 1,
            event.x + 1,
            event.y + 1,
            fill=color,
            outline="",
            tags="brush_cursor",
        )

    def _mouse_zoom(self, event: tk.Event) -> None:
        self._change_zoom(1.15 if event.delta > 0 else 1 / 1.15)

    def _change_zoom(self, multiplier: float) -> None:
        if self.editor is None:
            return
        self.zoom_factor = min(8.0, max(0.5, self.zoom_factor * multiplier))
        self.zoom_label.configure(text=f"{int(self.zoom_factor * 100)}%")
        self._draw_preview()

    def fit_to_canvas(self) -> None:
        self.zoom_factor = 1.0
        self.pan_offset = [0, 0]
        self.zoom_label.configure(text="適合畫面")
        self._draw_preview()

    def _start_pan(self, event: tk.Event) -> None:
        if self.editor is not None:
            self.pan_start = (event.x, event.y)
            self.canvas.configure(cursor="fleur")

    def _continue_pan(self, event: tk.Event) -> None:
        if self.pan_start is None:
            return
        self.pan_offset[0] += event.x - self.pan_start[0]
        self.pan_offset[1] += event.y - self.pan_start[1]
        self.pan_start = (event.x, event.y)
        self._draw_preview()

    def _end_pan(self, _event: tk.Event) -> None:
        self.pan_start = None
        self.canvas.configure(cursor="crosshair")

    def undo(self) -> None:
        if self.editor is not None and self.editor.undo():
            self._draw_preview()
            self.status_text.set("已復原上一步。")

    def reset_mask(self) -> None:
        if self.editor is None or not self.has_auto_cutout:
            return
        self.editor.reset()
        self._draw_preview()
        self.status_text.set("已重設為自動去背結果。")

    def smart_refine(self) -> None:
        if self.editor is None or not self.has_auto_cutout or self.is_processing:
            return
        if not self.editor.has_guidance():
            messagebox.showwarning(
                APP_TITLE,
                "請先用「擦除區域」標記背景，或用「還原區域」標記主體。",
            )
            return
        self.is_processing = True
        self.refine_button.configure(state="disabled", text="分析筆觸中…")
        self.process_button.configure(state="disabled")
        self.status_text.set("正在依照你的標記重新計算完整邊界…")
        threading.Thread(target=self._refine_worker, daemon=True).start()

    def _refine_worker(self) -> None:
        try:
            if self.editor is None:
                raise RuntimeError("沒有可精修的遮罩。")
            self.editor.smart_refine()
        except Exception as exc:
            self.root.after(0, lambda error=exc: self._finish_refining(error))
        else:
            self.root.after(0, self._finish_refining, None)

    def _finish_refining(self, error: Exception | None) -> None:
        self.is_processing = False
        self.refine_button.configure(state="normal", text="✦  再次智慧精修")
        self.process_button.configure(state="normal")
        if error is not None:
            self.status_text.set("智慧精修失敗，請調整標記後再試。")
            messagebox.showerror(APP_TITLE, str(error))
            return
        self._draw_preview()
        self.status_text.set("智慧精修完成。可繼續標記後再次執行。")

    def save_image(self) -> None:
        if self.editor is None:
            messagebox.showwarning(APP_TITLE, "請先完成自動去背。")
            return
        input_path = Path(self.selected_file.get())
        default_output = build_default_output_path(input_path)
        selected_path = filedialog.asksaveasfilename(title="儲存透明 PNG", defaultextension=".png", initialfile=default_output.name, initialdir=str(default_output.parent), filetypes=[("PNG Image", "*.png")])
        if not selected_path:
            return
        try:
            output_path = Path(selected_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            self.editor.render().save(output_path, format="PNG")
        except Exception as exc:
            messagebox.showerror(APP_TITLE, str(exc))
            return
        self.status_text.set(f"完成：{output_path}")
        messagebox.showinfo(APP_TITLE, f"透明 PNG 已儲存：\n{output_path}")


def run_app() -> None:
    root = ctk.CTk()
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    icon_path = bundle_root / "assets" / "icon.png"
    if icon_path.is_file():
        try:
            icon = tk.PhotoImage(file=str(icon_path))
            root.iconphoto(True, icon)
            root._app_icon = icon
        except tk.TclError:
            pass
    PngFactoryApp(root)
    root.mainloop()
