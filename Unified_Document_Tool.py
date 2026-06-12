from __future__ import annotations

import io
import os
import sys
import ctypes
import tkinter as tk
from dataclasses import dataclass
from io import BytesIO
from tkinter import filedialog, messagebox, ttk

import fitz
from PIL import Image, ImageOps, ImageSequence, ImageTk
from pypdf import PdfReader, PdfWriter

try:
    import cv2
    import numpy as np
except ImportError:
    cv2 = None
    np = None

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
except ImportError:
    DND_FILES = None
    TkinterDnD = None


APP_TITLE = "문서 도구 통합 프로그램"
APP_ID = "unified.document.tool"
ICON_FILENAME = "SCAN.ico"
APP_SUBTITLE = "PDF, 이미지 변환, 병합, 스캔 보정을 한 곳에서 처리합니다."

COLOR_BG = "#edf7ff"
COLOR_SURFACE = "#ffffff"
COLOR_SURFACE_ALT = "#e4f2ff"
COLOR_BORDER = "#b8d7f1"
COLOR_ACCENT = "#4b9fe1"
COLOR_ACCENT_DARK = "#2d79be"
COLOR_TEXT = "#16324a"
COLOR_MUTED = "#5d7f9d"
COLOR_LIST_BG = "#f8fcff"
COLOR_SELECT = "#cfe7fb"

PDF_EXTS = {".pdf"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp", ".gif"}
SCAN_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp"}
SUPPORTED_MERGE_EXTS = PDF_EXTS | IMAGE_EXTS

PAGE_SIZES_MM = {
    "원본 크기 유지": None,
    "A4": (210, 297),
    "Letter": (216, 279),
}
FIT_MODES = ["맞춤", "채우기", "원본 100%"]


def apply_app_id():
    if not sys.platform.startswith("win"):
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass


def apply_window_icon(window):
    icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ICON_FILENAME)
    if not os.path.exists(icon_path):
        return
    try:
        window.iconbitmap(icon_path)
    except Exception:
        pass


def show_error(parent, title, error):
    messagebox.showerror(title, str(error), parent=parent)


def configure_app_styles(root):
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass

    root.configure(bg=COLOR_BG)

    style.configure(".", background=COLOR_BG, foreground=COLOR_TEXT)
    style.configure("App.TFrame", background=COLOR_BG)
    style.configure("Surface.TFrame", background=COLOR_SURFACE)
    style.configure("Toolbar.TFrame", background=COLOR_SURFACE)
    style.configure("Header.TFrame", background=COLOR_ACCENT)
    style.configure("HeaderText.TLabel", background=COLOR_ACCENT, foreground="#f7fbff")
    style.configure("HeaderSub.TLabel", background=COLOR_ACCENT, foreground="#dceeff")
    style.configure("Title.TLabel", background=COLOR_SURFACE, foreground=COLOR_TEXT, font=("Malgun Gothic", 11, "bold"))
    style.configure("Muted.TLabel", background=COLOR_SURFACE, foreground=COLOR_MUTED)
    style.configure(
        "TNotebook",
        background=COLOR_BG,
        borderwidth=0,
        tabmargins=(8, 0, 8, 0),
    )
    style.configure(
        "TNotebook.Tab",
        background=COLOR_SURFACE_ALT,
        foreground=COLOR_TEXT,
        padding=(18, 9),
        font=("Malgun Gothic", 10, "bold"),
        borderwidth=0,
    )
    style.map(
        "TNotebook.Tab",
        background=[("selected", COLOR_SURFACE), ("active", "#d9eeff")],
        foreground=[("selected", COLOR_ACCENT_DARK)],
    )
    style.configure(
        "TButton",
        background=COLOR_SURFACE_ALT,
        foreground=COLOR_TEXT,
        bordercolor=COLOR_BORDER,
        lightcolor=COLOR_SURFACE_ALT,
        darkcolor=COLOR_SURFACE_ALT,
        focusthickness=1,
        focuscolor=COLOR_BORDER,
        padding=(10, 7),
    )
    style.map("TButton", background=[("active", "#d9eeff"), ("pressed", "#c2e3ff")])
    style.configure(
        "Accent.TButton",
        background=COLOR_ACCENT,
        foreground="#f7fbff",
        bordercolor=COLOR_ACCENT,
        lightcolor=COLOR_ACCENT,
        darkcolor=COLOR_ACCENT,
        padding=(12, 8),
    )
    style.map("Accent.TButton", background=[("active", COLOR_ACCENT_DARK), ("pressed", COLOR_ACCENT_DARK)])
    style.configure(
        "TLabelframe",
        background=COLOR_SURFACE,
        foreground=COLOR_TEXT,
        bordercolor=COLOR_BORDER,
        relief="solid",
    )
    style.configure("TLabelframe.Label", background=COLOR_SURFACE, foreground=COLOR_ACCENT_DARK, font=("Malgun Gothic", 10, "bold"))
    style.configure("TCheckbutton", background=COLOR_SURFACE, foreground=COLOR_TEXT)
    style.configure("TCombobox", fieldbackground=COLOR_LIST_BG)
    style.configure("TSpinbox", fieldbackground=COLOR_LIST_BG)
    style.configure(
        "Horizontal.TProgressbar",
        troughcolor="#dbeeff",
        background=COLOR_ACCENT,
        bordercolor=COLOR_BORDER,
        lightcolor=COLOR_ACCENT,
        darkcolor=COLOR_ACCENT,
    )


def style_listbox(widget):
    widget.configure(
        bg=COLOR_LIST_BG,
        fg=COLOR_TEXT,
        selectbackground=COLOR_SELECT,
        selectforeground=COLOR_TEXT,
        activestyle="none",
        bd=0,
        relief="flat",
        highlightthickness=1,
        highlightbackground=COLOR_BORDER,
        highlightcolor=COLOR_ACCENT,
    )


def style_preview_label(widget, empty_text):
    widget.configure(
        text=empty_text,
        bg=COLOR_LIST_BG,
        fg=COLOR_MUTED,
        relief="flat",
        bd=0,
        highlightthickness=1,
        highlightbackground=COLOR_BORDER,
        highlightcolor=COLOR_ACCENT,
        padx=16,
        pady=16,
    )


def build_section_intro(parent, title, text):
    wrap = ttk.Frame(parent, style="Surface.TFrame")
    wrap.pack(fill="x", pady=(0, 8))
    ttk.Label(wrap, text=title, style="Title.TLabel").pack(anchor="w")
    ttk.Label(wrap, text=text, style="Muted.TLabel", wraplength=420, justify="left").pack(anchor="w", pady=(4, 0))
    return wrap


def normalize_image_to_rgb(pil_img: Image.Image) -> Image.Image:
    pil_img = ImageOps.exif_transpose(pil_img)

    if pil_img.mode in ("RGBA", "LA"):
        rgba = pil_img.convert("RGBA")
        bg = Image.new("RGB", rgba.size, "white")
        bg.paste(rgba, mask=rgba.getchannel("A"))
        return bg

    if pil_img.mode == "P":
        rgba = pil_img.convert("RGBA")
        bg = Image.new("RGB", rgba.size, "white")
        bg.paste(rgba, mask=rgba.getchannel("A"))
        return bg

    if pil_img.mode != "RGB":
        return pil_img.convert("RGB")

    return pil_img


def get_image_frame_count(path: str) -> int:
    try:
        img = Image.open(path)
        count = sum(1 for _ in ImageSequence.Iterator(img))
        img.close()
        return max(1, count)
    except Exception:
        return 1


def load_image_frame(path: str, frame_index: int = 0) -> Image.Image:
    img = Image.open(path)
    try:
        img.seek(frame_index)
    except EOFError:
        img.seek(0)
    copied = img.copy()
    img.close()
    return normalize_image_to_rgb(copied)


def render_pdf_page(path: str, page_index: int, dpi: int = 120) -> Image.Image:
    doc = fitz.open(path)
    try:
        page = doc.load_page(page_index)
        pix = page.get_pixmap(dpi=dpi, alpha=False)
        return Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    finally:
        doc.close()


def create_preview_photo(pil_img: Image.Image, max_size=(430, 520), master=None):
    img = pil_img.copy()
    img.thumbnail(max_size, Image.LANCZOS)
    return ImageTk.PhotoImage(img, master=master)


def page_has_meaningful_non_image_content(page) -> bool:
    """Return True when the page contains text/vector content that should be rendered."""
    try:
        if page.get_text("text").strip():
            return True
    except Exception:
        pass

    try:
        if page.get_drawings():
            return True
    except Exception:
        pass

    try:
        if page.first_annot is not None:
            return True
    except Exception:
        pass

    return False


def rect_covers_page(page_rect, candidate_rect, tol_ratio=0.98, edge_tol_ratio=0.03) -> bool:
    page_area = page_rect.get_area()
    if page_area <= 0:
        return False

    cover_ratio = candidate_rect.get_area() / page_area
    if cover_ratio < tol_ratio:
        return False

    edge_tol = min(page_rect.width, page_rect.height) * edge_tol_ratio
    return (
        abs(candidate_rect.x0 - page_rect.x0) <= edge_tol
        and abs(candidate_rect.y0 - page_rect.y0) <= edge_tol
        and abs(candidate_rect.x1 - page_rect.x1) <= edge_tol
        and abs(candidate_rect.y1 - page_rect.y1) <= edge_tol
    )


def extract_fullpage_image_if_any(pdf_document, page, tol_ratio=0.98):
    try:
        # If the page has text, lines, boxes, or annotations, render the whole page.
        # This avoids returning only a background/border image for certificate-like PDFs.
        if page_has_meaningful_non_image_content(page):
            return None

        images = page.get_images(full=True)
        if not images:
            return None

        page_rect = page.rect
        if len(images) != 1:
            return None

        for image_info in images:
            xref = image_info[0]
            rects = page.get_image_rects(xref)
            if len(rects) != 1:
                continue
            for rect in rects:
                if rect_covers_page(page_rect, rect, tol_ratio=tol_ratio):
                    pix = fitz.Pixmap(pdf_document, xref)
                    try:
                        if pix.alpha:
                            rgb = fitz.Pixmap(fitz.csRGB, pix)
                            image_bytes = rgb.tobytes("png")
                            rgb = None
                        else:
                            image_bytes = pix.tobytes("png")
                    finally:
                        pix = None
                    return Image.open(io.BytesIO(image_bytes))
    except Exception:
        return None
    return None


def build_pdf_canvas(img: Image.Image, page_size_name: str, orientation: str, fit_mode: str, margin_mm: int, dpi: int):
    img = normalize_image_to_rgb(img)
    page_size = PAGE_SIZES_MM[page_size_name]
    if page_size is None:
        return img.copy()

    w_mm, h_mm = page_size
    if orientation == "가로":
        w_mm, h_mm = h_mm, w_mm

    px_per_mm = dpi / 25.4
    page_w = int(round(w_mm * px_per_mm))
    page_h = int(round(h_mm * px_per_mm))
    margin_px = int(round(margin_mm * px_per_mm))
    target_w = max(page_w - 2 * margin_px, 1)
    target_h = max(page_h - 2 * margin_px, 1)
    canvas = Image.new("RGB", (page_w, page_h), "white")

    if fit_mode == "원본 100%":
        paste = img.copy()
        if paste.width > target_w or paste.height > target_h:
            paste.thumbnail((target_w, target_h), Image.LANCZOS)
        paste_x = margin_px
        paste_y = margin_px
    elif fit_mode == "맞춤":
        paste = img.copy()
        paste.thumbnail((target_w, target_h), Image.LANCZOS)
        paste_x = margin_px + (target_w - paste.width) // 2
        paste_y = margin_px + (target_h - paste.height) // 2
    else:
        scale = max(target_w / img.width, target_h / img.height)
        new_w = max(1, int(round(img.width * scale)))
        new_h = max(1, int(round(img.height * scale)))
        resized = img.resize((new_w, new_h), Image.LANCZOS)
        left = max((new_w - target_w) // 2, 0)
        top = max((new_h - target_h) // 2, 0)
        paste = resized.crop((left, top, left + target_w, top + target_h))
        paste_x = margin_px
        paste_y = margin_px

    canvas.paste(paste, (paste_x, paste_y))
    return canvas


def unique_path(path: str) -> str:
    base, ext = os.path.splitext(path)
    candidate = path
    index = 1
    while os.path.exists(candidate):
        candidate = f"{base}({index}){ext}"
        index += 1
    return candidate


@dataclass
class MergePage:
    src_path: str
    src_type: str
    page_index: int
    label: str


class DnDMixin:
    def bind_drop_widget(self, widget, callback):
        if not (TkinterDnD and DND_FILES):
            return
        widget.drop_target_register(DND_FILES)
        widget.dnd_bind("<<Drop>>", callback)


class MergeTab(ttk.Frame, DnDMixin):
    def __init__(self, master):
        super().__init__(master, padding=14, style="Surface.TFrame")
        self.pages: list[MergePage] = []
        self.preview_photo = None
        self.only_selected_var = tk.BooleanVar(value=False)
        self._build_ui()

    def _build_ui(self):
        build_section_intro(self, "페이지 단위 병합", "PDF와 이미지를 한 목록으로 정리하고 순서를 바꿔 원하는 결과 PDF로 저장합니다.")
        btns = ttk.Frame(self, style="Toolbar.TFrame")
        btns.pack(fill="x", pady=(0, 8))

        ttk.Button(btns, text="PDF/이미지 추가", command=self.add_files).pack(side="left")
        ttk.Button(btns, text="위로", command=lambda: self.move_selected(-1)).pack(side="left", padx=4)
        ttk.Button(btns, text="아래로", command=lambda: self.move_selected(1)).pack(side="left", padx=4)
        ttk.Button(btns, text="선택 삭제", command=self.remove_selected).pack(side="left", padx=4)
        ttk.Button(btns, text="전체 비우기", command=self.clear_all).pack(side="left", padx=4)
        ttk.Checkbutton(btns, text="선택 페이지만 내보내기", variable=self.only_selected_var).pack(side="left", padx=(16, 0))
        ttk.Button(btns, text="PDF 저장", command=self.export_pdf).pack(side="right")

        body = ttk.Panedwindow(self, orient="horizontal")
        body.pack(fill="both", expand=True)

        left = ttk.Frame(body, style="Surface.TFrame")
        right = ttk.Frame(body, style="Surface.TFrame")
        body.add(left, weight=3)
        body.add(right, weight=2)

        self.page_list = tk.Listbox(left, selectmode=tk.EXTENDED)
        self.page_list.pack(side="left", fill="both", expand=True)
        style_listbox(self.page_list)
        self.page_list.bind("<<ListboxSelect>>", self.on_select)
        self.bind_drop_widget(self.page_list, self.on_drop)

        scroll = ttk.Scrollbar(left, orient="vertical", command=self.page_list.yview)
        scroll.pack(side="right", fill="y")
        self.page_list.configure(yscrollcommand=scroll.set)

        hint = "PDF 또는 이미지 파일을 추가하면 PDF는 페이지 단위로, 이미지는 이미지 단위로 목록에 들어갑니다."
        ttk.Label(right, text=hint, wraplength=360, foreground="#555").pack(anchor="w", pady=(0, 8))

        self.preview_label = tk.Label(right, text="미리보기 없음", bg="#f3f4f6", relief="solid", bd=1)
        style_preview_label(self.preview_label, "미리보기 없음")
        self.preview_label.pack(fill="both", expand=True)

    def on_drop(self, event):
        try:
            paths = [p.strip().strip("{}") for p in self.tk.splitlist(event.data)]
        except Exception:
            paths = [event.data]
        self._load_paths(paths)

    def add_files(self):
        paths = filedialog.askopenfilenames(
            parent=self,
            title="PDF 또는 이미지 선택",
            filetypes=[("지원 파일", "*.pdf *.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp *.gif"), ("모든 파일", "*.*")],
        )
        if paths:
            self._load_paths(paths)

    def _load_paths(self, paths):
        added = 0
        for path in paths:
            if not os.path.isfile(path):
                continue
            ext = os.path.splitext(path)[1].lower()
            if ext in PDF_EXTS:
                added += self._load_pdf(path)
            elif ext in IMAGE_EXTS:
                added += self._load_image(path)
        if added:
            self.refresh_list()

    def _load_pdf(self, path):
        count = 0
        try:
            doc = fitz.open(path)
            total = len(doc)
            doc.close()
            for idx in range(total):
                self.pages.append(MergePage(path, "pdf", idx, f"[PDF] {os.path.basename(path)} - {idx + 1}페이지"))
                count += 1
        except Exception as exc:
            show_error(self, "PDF 로드 실패", exc)
        return count

    def _load_image(self, path):
        count = 0
        try:
            frame_count = get_image_frame_count(path)
            for idx in range(frame_count):
                label = f"[IMG] {os.path.basename(path)}"
                if frame_count > 1:
                    label += f" - frame {idx + 1}"
                self.pages.append(MergePage(path, "image", idx, label))
                count += 1
        except Exception as exc:
            show_error(self, "이미지 로드 실패", exc)
        return count

    def refresh_list(self):
        selected = self.page_list.curselection()
        self.page_list.delete(0, tk.END)
        for page in self.pages:
            self.page_list.insert(tk.END, page.label)
        for idx in selected:
            if idx < len(self.pages):
                self.page_list.selection_set(idx)

    def on_select(self, _event=None):
        indices = self.page_list.curselection()
        if not indices:
            self.preview_label.configure(image="", text="미리보기 없음")
            self.preview_photo = None
            return
        page = self.pages[indices[0]]
        try:
            if page.src_type == "pdf":
                pil = render_pdf_page(page.src_path, page.page_index, dpi=120)
            else:
                pil = load_image_frame(page.src_path, page.page_index)
            self.preview_photo = create_preview_photo(pil, master=self.preview_label)
            self.preview_label.configure(image=self.preview_photo, text="")
        except Exception as exc:
            self.preview_label.configure(image="", text="미리보기 실패")
            show_error(self, "미리보기 실패", exc)

    def move_selected(self, direction):
        indices = list(self.page_list.curselection())
        if not indices:
            return
        if direction < 0:
            for idx in indices:
                if idx == 0:
                    continue
                self.pages[idx - 1], self.pages[idx] = self.pages[idx], self.pages[idx - 1]
        else:
            for idx in reversed(indices):
                if idx >= len(self.pages) - 1:
                    continue
                self.pages[idx + 1], self.pages[idx] = self.pages[idx], self.pages[idx + 1]
        self.refresh_list()
        for idx in indices:
            new_idx = max(0, min(len(self.pages) - 1, idx + direction))
            self.page_list.selection_set(new_idx)
        self.on_select()

    def remove_selected(self):
        remove_set = set(self.page_list.curselection())
        if not remove_set:
            return
        self.pages = [page for i, page in enumerate(self.pages) if i not in remove_set]
        self.refresh_list()
        self.on_select()

    def clear_all(self):
        self.pages.clear()
        self.refresh_list()
        self.on_select()

    def export_pdf(self):
        if not self.pages:
            messagebox.showwarning("안내", "병합할 페이지가 없습니다.", parent=self)
            return

        indices = list(self.page_list.curselection())
        export_pages = self.pages
        if self.only_selected_var.get():
            if not indices:
                messagebox.showwarning("안내", "선택 페이지가 없습니다.", parent=self)
                return
            export_pages = [self.pages[i] for i in indices]

        out_path = filedialog.asksaveasfilename(
            parent=self,
            title="저장할 PDF 선택",
            defaultextension=".pdf",
            filetypes=[("PDF files", "*.pdf")],
            initialfile="merged.pdf",
        )
        if not out_path:
            return

        readers = {}
        image_buffers = []
        writer = PdfWriter()

        try:
            for page in export_pages:
                if page.src_type == "pdf":
                    reader = readers.get(page.src_path)
                    if reader is None:
                        reader = PdfReader(page.src_path, strict=False)
                        if reader.is_encrypted:
                            reader.decrypt("")
                        readers[page.src_path] = reader
                    writer.add_page(reader.pages[page.page_index])
                else:
                    pil = load_image_frame(page.src_path, page.page_index)
                    buf = BytesIO()
                    pil.save(buf, format="PDF", resolution=100.0)
                    buf.seek(0)
                    image_buffers.append(buf)
                    reader = PdfReader(buf, strict=False)
                    writer.add_page(reader.pages[0])

            with open(out_path, "wb") as fp:
                writer.write(fp)
            messagebox.showinfo("완료", f"저장되었습니다.\n{out_path}", parent=self)
        except Exception as exc:
            show_error(self, "병합 실패", exc)


class ImageToPdfTab(ttk.Frame, DnDMixin):
    def __init__(self, master):
        super().__init__(master, padding=14, style="Surface.TFrame")
        self.preview_photo = None
        self._build_ui()

    def _build_ui(self):
        build_section_intro(self, "이미지에서 PDF 만들기", "여러 이미지를 모아 단일 PDF로 저장하거나 각 이미지별 PDF를 순서대로 생성합니다.")
        top = ttk.Frame(self, style="Toolbar.TFrame")
        top.pack(fill="x", pady=(0, 8))

        ttk.Button(top, text="이미지 추가", command=self.add_files).pack(side="left")
        ttk.Button(top, text="폴더 추가", command=self.add_folder).pack(side="left", padx=4)
        ttk.Button(top, text="위로", command=lambda: self.move_selected(-1)).pack(side="left", padx=4)
        ttk.Button(top, text="아래로", command=lambda: self.move_selected(1)).pack(side="left", padx=4)
        ttk.Button(top, text="선택 삭제", command=self.remove_selected).pack(side="left", padx=4)
        ttk.Button(top, text="전체 비우기", command=self.clear_all).pack(side="left", padx=4)

        body = ttk.Panedwindow(self, orient="horizontal")
        body.pack(fill="both", expand=True)
        left = ttk.Frame(body, style="Surface.TFrame")
        right = ttk.Frame(body, style="Surface.TFrame")
        body.add(left, weight=3)
        body.add(right, weight=2)

        self.image_list = tk.Listbox(left, selectmode=tk.EXTENDED)
        self.image_list.pack(side="left", fill="both", expand=True)
        style_listbox(self.image_list)
        self.image_list.bind("<<ListboxSelect>>", self.on_select)
        self.bind_drop_widget(self.image_list, self.on_drop)

        scroll = ttk.Scrollbar(left, orient="vertical", command=self.image_list.yview)
        scroll.pack(side="right", fill="y")
        self.image_list.configure(yscrollcommand=scroll.set)

        opt = ttk.LabelFrame(right, text="PDF 옵션", padding=10)
        opt.pack(fill="x")

        self.page_size_var = tk.StringVar(value="원본 크기 유지")
        self.orientation_var = tk.StringVar(value="세로")
        self.fit_var = tk.StringVar(value="맞춤")
        self.margin_var = tk.IntVar(value=0)
        self.dpi_var = tk.IntVar(value=300)

        self._add_row(opt, 0, "페이지 크기", ttk.Combobox(opt, textvariable=self.page_size_var, values=list(PAGE_SIZES_MM.keys()), state="readonly"))
        self._add_row(opt, 1, "방향", ttk.Combobox(opt, textvariable=self.orientation_var, values=["세로", "가로"], state="readonly"))
        self._add_row(opt, 2, "배치", ttk.Combobox(opt, textvariable=self.fit_var, values=FIT_MODES, state="readonly"))
        self._add_row(opt, 3, "여백(mm)", ttk.Spinbox(opt, from_=0, to=50, textvariable=self.margin_var, width=8))
        self._add_row(opt, 4, "DPI", ttk.Spinbox(opt, from_=72, to=600, textvariable=self.dpi_var, width=8))

        action = ttk.Frame(right)
        action.pack(fill="x", pady=8)
        ttk.Button(action, text="하나의 PDF로 저장", command=self.export_merged_pdf).pack(fill="x")
        ttk.Button(action, text="각 이미지별 PDF 저장", command=self.export_each_pdf).pack(fill="x", pady=(6, 0))

        self.preview_label = tk.Label(right, text="미리보기 없음", bg="#f3f4f6", relief="solid", bd=1)
        style_preview_label(self.preview_label, "미리보기 없음")
        self.preview_label.pack(fill="both", expand=True, pady=(8, 0))

    def _add_row(self, parent, row, text, widget):
        ttk.Label(parent, text=text).grid(row=row, column=0, sticky="w", pady=4)
        widget.grid(row=row, column=1, sticky="ew", pady=4)
        parent.columnconfigure(1, weight=1)

    def current_paths(self):
        return list(self.image_list.get(0, tk.END))

    def on_drop(self, event):
        try:
            paths = [p.strip().strip("{}") for p in self.tk.splitlist(event.data)]
        except Exception:
            paths = [event.data]
        self._add_images(paths)

    def add_files(self):
        paths = filedialog.askopenfilenames(
            parent=self,
            title="이미지 선택",
            filetypes=[("Image files", "*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp *.gif")],
        )
        if paths:
            self._add_images(paths)

    def add_folder(self):
        directory = filedialog.askdirectory(parent=self, title="이미지 폴더 선택")
        if not directory:
            return
        paths = []
        for root, _, files in os.walk(directory):
            for name in files:
                if os.path.splitext(name)[1].lower() in IMAGE_EXTS:
                    paths.append(os.path.join(root, name))
        self._add_images(paths)

    def _add_images(self, paths):
        existing = {os.path.normcase(os.path.abspath(p)) for p in self.current_paths()}
        for path in paths:
            if not os.path.isfile(path):
                continue
            if os.path.splitext(path)[1].lower() not in IMAGE_EXTS:
                continue
            norm = os.path.normcase(os.path.abspath(path))
            if norm in existing:
                continue
            self.image_list.insert(tk.END, os.path.abspath(path))
            existing.add(norm)
        self.on_select()

    def on_select(self, _event=None):
        selection = self.image_list.curselection()
        if not selection:
            self.preview_label.configure(image="", text="미리보기 없음")
            self.preview_photo = None
            return
        path = self.image_list.get(selection[0])
        try:
            img = load_image_frame(path, 0)
            self.preview_photo = create_preview_photo(img, master=self.preview_label)
            self.preview_label.configure(image=self.preview_photo, text="")
        except Exception as exc:
            show_error(self, "미리보기 실패", exc)

    def move_selected(self, direction):
        indices = list(self.image_list.curselection())
        if not indices:
            return
        items = self.current_paths()
        if direction < 0:
            for idx in indices:
                if idx == 0:
                    continue
                items[idx - 1], items[idx] = items[idx], items[idx - 1]
        else:
            for idx in reversed(indices):
                if idx >= len(items) - 1:
                    continue
                items[idx + 1], items[idx] = items[idx], items[idx + 1]
        self.image_list.delete(0, tk.END)
        for item in items:
            self.image_list.insert(tk.END, item)
        for idx in indices:
            self.image_list.selection_set(max(0, min(len(items) - 1, idx + direction)))
        self.on_select()

    def remove_selected(self):
        for idx in reversed(self.image_list.curselection()):
            self.image_list.delete(idx)
        self.on_select()

    def clear_all(self):
        self.image_list.delete(0, tk.END)
        self.on_select()

    def _build_images_for_pdf(self, paths):
        results = []
        for path in paths:
            img = load_image_frame(path, 0)
            canvas = build_pdf_canvas(
                img,
                self.page_size_var.get(),
                self.orientation_var.get(),
                self.fit_var.get(),
                int(self.margin_var.get()),
                int(self.dpi_var.get()),
            )
            results.append(canvas)
        return results

    def export_merged_pdf(self):
        paths = self.current_paths()
        if not paths:
            messagebox.showwarning("안내", "이미지를 추가해 주세요.", parent=self)
            return
        default_name = os.path.splitext(os.path.basename(paths[0]))[0] + ".pdf"
        out_path = filedialog.asksaveasfilename(parent=self, defaultextension=".pdf", initialfile=default_name, filetypes=[("PDF files", "*.pdf")])
        if not out_path:
            return
        try:
            images = self._build_images_for_pdf(paths)
            images[0].save(out_path, "PDF", save_all=True, append_images=images[1:], resolution=int(self.dpi_var.get()))
            messagebox.showinfo("완료", f"저장되었습니다.\n{out_path}", parent=self)
        except Exception as exc:
            show_error(self, "PDF 저장 실패", exc)

    def export_each_pdf(self):
        paths = self.current_paths()
        if not paths:
            messagebox.showwarning("안내", "이미지를 추가해 주세요.", parent=self)
            return
        ok_count = 0
        fail_count = 0
        for path in paths:
            try:
                img = load_image_frame(path, 0)
                canvas = build_pdf_canvas(
                    img,
                    self.page_size_var.get(),
                    self.orientation_var.get(),
                    self.fit_var.get(),
                    int(self.margin_var.get()),
                    int(self.dpi_var.get()),
                )
                save_path = unique_path(os.path.splitext(path)[0] + ".pdf")
                canvas.save(save_path, "PDF", resolution=int(self.dpi_var.get()))
                ok_count += 1
            except Exception:
                fail_count += 1
        messagebox.showinfo("완료", f"개별 PDF 저장 완료\n성공: {ok_count}개 / 실패: {fail_count}개", parent=self)


class PdfToImageTab(ttk.Frame, DnDMixin):
    def __init__(self, master):
        super().__init__(master, padding=14, style="Surface.TFrame")
        self.output_folder_var = tk.StringVar(value="")
        self.format_var = tk.StringVar(value="png")
        self.dpi_var = tk.IntVar(value=300)
        self.use_source_folder_var = tk.BooleanVar(value=True)
        self._build_ui()

    def _build_ui(self):
        build_section_intro(self, "PDF에서 이미지 추출", "페이지별 이미지 저장에 집중한 탭입니다. 문서형 PDF는 전체 페이지 렌더링을 우선 사용합니다.")
        top = ttk.Frame(self, style="Toolbar.TFrame")
        top.pack(fill="x", pady=(0, 8))

        ttk.Button(top, text="PDF 추가", command=self.add_files).pack(side="left")
        ttk.Button(top, text="선택 삭제", command=self.remove_selected).pack(side="left", padx=4)
        ttk.Button(top, text="전체 비우기", command=self.clear_all).pack(side="left", padx=4)
        ttk.Button(top, text="변환 시작", command=self.convert).pack(side="right")

        self.pdf_list = tk.Listbox(self, selectmode=tk.EXTENDED, height=8)
        self.pdf_list.pack(fill="both", expand=True)
        style_listbox(self.pdf_list)
        self.bind_drop_widget(self.pdf_list, self.on_drop)

        save_opt = ttk.LabelFrame(self, text="저장 위치", padding=10)
        save_opt.pack(fill="x", pady=8)

        ttk.Checkbutton(save_opt, text="원본 PDF 폴더 기준으로 저장", variable=self.use_source_folder_var, command=self.update_save_state).pack(anchor="w")
        row = ttk.Frame(save_opt)
        row.pack(fill="x", pady=(6, 0))
        self.output_entry = ttk.Entry(row, textvariable=self.output_folder_var)
        self.output_entry.pack(side="left", fill="x", expand=True)
        self.output_button = ttk.Button(row, text="찾아보기", command=self.browse_output_folder)
        self.output_button.pack(side="left", padx=(6, 0))

        opt = ttk.LabelFrame(self, text="변환 옵션", padding=10)
        opt.pack(fill="x")
        ttk.Label(opt, text="출력 형식").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Combobox(opt, textvariable=self.format_var, values=["png", "jpg", "tiff", "bmp", "gif"], state="readonly").grid(row=0, column=1, sticky="ew", pady=4)
        ttk.Label(opt, text="DPI").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Spinbox(opt, from_=72, to=600, textvariable=self.dpi_var, width=8).grid(row=1, column=1, sticky="w", pady=4)
        opt.columnconfigure(1, weight=1)

        self.progress = ttk.Progressbar(self, mode="determinate")
        self.progress.pack(fill="x", pady=(8, 0))
        self.status_label = ttk.Label(self, text="대기 중")
        self.status_label.pack(anchor="w", pady=(4, 0))

        self.update_save_state()

    def current_paths(self):
        return list(self.pdf_list.get(0, tk.END))

    def on_drop(self, event):
        try:
            paths = [p.strip().strip("{}") for p in self.tk.splitlist(event.data)]
        except Exception:
            paths = [event.data]
        self._add_pdfs(paths)

    def add_files(self):
        paths = filedialog.askopenfilenames(parent=self, title="PDF 선택", filetypes=[("PDF files", "*.pdf")])
        if paths:
            self._add_pdfs(paths)

    def _add_pdfs(self, paths):
        existing = {os.path.normcase(os.path.abspath(p)) for p in self.current_paths()}
        for path in paths:
            if not os.path.isfile(path) or os.path.splitext(path)[1].lower() != ".pdf":
                continue
            norm = os.path.normcase(os.path.abspath(path))
            if norm in existing:
                continue
            self.pdf_list.insert(tk.END, os.path.abspath(path))
            existing.add(norm)

    def remove_selected(self):
        for idx in reversed(self.pdf_list.curselection()):
            self.pdf_list.delete(idx)

    def clear_all(self):
        self.pdf_list.delete(0, tk.END)

    def browse_output_folder(self):
        path = filedialog.askdirectory(parent=self, title="출력 폴더 선택")
        if path:
            self.output_folder_var.set(path)

    def update_save_state(self):
        state = "disabled" if self.use_source_folder_var.get() else "normal"
        self.output_entry.configure(state=state)
        self.output_button.configure(state=state)

    def convert(self):
        paths = self.current_paths()
        if not paths:
            messagebox.showwarning("안내", "PDF를 추가해 주세요.", parent=self)
            return

        if not self.use_source_folder_var.get():
            out_root = self.output_folder_var.get().strip()
            if not out_root or not os.path.isdir(out_root):
                messagebox.showwarning("안내", "유효한 출력 폴더를 지정해 주세요.", parent=self)
                return

        total_files = len(paths)
        fmt = self.format_var.get().lower()
        dpi = int(self.dpi_var.get())
        self.progress.configure(maximum=total_files, value=0)

        try:
            for file_index, file_path in enumerate(paths, start=1):
                pdf_name = os.path.splitext(os.path.basename(file_path))[0]
                if self.use_source_folder_var.get():
                    target_dir = os.path.join(os.path.dirname(file_path), pdf_name)
                else:
                    target_dir = os.path.join(self.output_folder_var.get().strip(), pdf_name)
                os.makedirs(target_dir, exist_ok=True)

                with fitz.open(file_path) as doc:
                    total_pages = len(doc)
                    for page_number in range(total_pages):
                        page = doc.load_page(page_number)
                        img = extract_fullpage_image_if_any(doc, page)
                        if img is None:
                            pix = page.get_pixmap(dpi=dpi, alpha=False)
                            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                        if fmt in ("jpg", "jpeg"):
                            img = normalize_image_to_rgb(img)
                        elif fmt == "gif" and img.mode == "P":
                            img = img.convert("RGBA")

                        if total_pages == 1:
                            filename = f"{pdf_name}.{fmt}"
                        else:
                            filename = f"{pdf_name}_page_{page_number + 1}.{fmt}"
                        save_path = os.path.join(target_dir, filename)

                        save_kwargs = {}
                        if fmt in ("jpg", "jpeg"):
                            save_kwargs.update({"quality": 95, "optimize": True})
                        if fmt == "tiff":
                            save_kwargs.update({"compression": "tiff_lzw"})
                        img.save(save_path, **save_kwargs)

                self.progress["value"] = file_index
                self.status_label.config(text=f"{file_index}/{total_files} 변환 완료: {os.path.basename(file_path)}")
                self.update_idletasks()

            self.status_label.config(text="모든 PDF 변환 완료")
            messagebox.showinfo("완료", "PDF를 이미지로 변환했습니다.", parent=self)
        except Exception as exc:
            self.status_label.config(text="변환 실패")
            show_error(self, "PDF 변환 실패", exc)


class ScanToPdfTab(ttk.Frame, DnDMixin):
    def __init__(self, master):
        super().__init__(master, padding=14, style="Surface.TFrame")
        self.file_paths: list[str] = []
        self.original_photo = None
        self.processed_photo = None
        self.processed_cache: dict[str, Image.Image] = {}
        self._build_ui()

    def _build_ui(self):
        if cv2 is None or np is None:
            ttk.Label(self, text="이 탭은 opencv-python 설치가 필요합니다.\npip install opencv-python", foreground="#b91c1c").pack(anchor="w")
            return

        build_section_intro(self, "스캔 보정 PDF", "문서 사진을 정리된 인쇄물 느낌으로 보정하고 선택 파일 또는 전체를 PDF로 저장합니다.")
        top = ttk.Frame(self, style="Toolbar.TFrame")
        top.pack(fill="x", pady=(0, 8))
        ttk.Button(top, text="이미지 추가", command=self.add_files).pack(side="left")
        ttk.Button(top, text="선택 파일만 PDF", command=self.export_selected_pdf).pack(side="left", padx=4)
        ttk.Button(top, text="전체 병합 PDF", command=self.export_merged_pdf).pack(side="left", padx=4)
        ttk.Button(top, text="전체 비우기", command=self.clear_all).pack(side="right")

        self.listbox = tk.Listbox(self, height=8)
        self.listbox.pack(fill="x")
        style_listbox(self.listbox)
        self.listbox.bind("<<ListboxSelect>>", self.on_select)
        self.bind_drop_widget(self.listbox, self.on_drop)

        self.status_label = ttk.Label(self, text="대기 중")
        self.status_label.pack(anchor="w", pady=(6, 6))

        preview_wrap = ttk.Frame(self)
        preview_wrap.pack(fill="both", expand=True)

        left = ttk.LabelFrame(preview_wrap, text="원본", padding=6)
        right = ttk.LabelFrame(preview_wrap, text="보정 결과", padding=6)
        left.pack(side="left", fill="both", expand=True, padx=(0, 4))
        right.pack(side="left", fill="both", expand=True, padx=(4, 0))

        self.original_label = tk.Label(left, text="이미지 선택", bg="#f8fafc", relief="solid", bd=1)
        style_preview_label(self.original_label, "이미지 선택")
        self.original_label.pack(fill="both", expand=True)
        self.processed_label = tk.Label(right, text="보정 결과", bg="#f8fafc", relief="solid", bd=1)
        style_preview_label(self.processed_label, "보정 결과")
        self.processed_label.pack(fill="both", expand=True)

    def on_drop(self, event):
        try:
            paths = [p.strip().strip("{}") for p in self.tk.splitlist(event.data)]
        except Exception:
            paths = [event.data]
        self._add_images(paths)

    def add_files(self):
        paths = filedialog.askopenfilenames(parent=self, title="이미지 선택", filetypes=[("Image files", "*.png *.jpg *.jpeg *.bmp")])
        if paths:
            self._add_images(paths)

    def _add_images(self, paths):
        existing = {os.path.normcase(os.path.abspath(p)) for p in self.file_paths}
        added = False
        for path in paths:
            if not os.path.isfile(path):
                continue
            if os.path.splitext(path)[1].lower() not in SCAN_IMAGE_EXTS:
                continue
            norm = os.path.normcase(os.path.abspath(path))
            if norm in existing:
                continue
            self.file_paths.append(os.path.abspath(path))
            self.listbox.insert(tk.END, os.path.basename(path))
            existing.add(norm)
            added = True
        if added:
            last = len(self.file_paths) - 1
            self.listbox.selection_clear(0, tk.END)
            self.listbox.selection_set(last)
            self.on_select()

    def clear_all(self):
        self.file_paths.clear()
        self.processed_cache.clear()
        self.listbox.delete(0, tk.END)
        self.original_label.configure(image="", text="이미지 선택")
        self.processed_label.configure(image="", text="보정 결과")
        self.status_label.config(text="목록을 비웠습니다.")

    def _read_image_cv(self, path):
        data = np.fromfile(path, dtype=np.uint8)
        if data.size == 0:
            return None
        return cv2.imdecode(data, cv2.IMREAD_COLOR)

    def _enhance_scanned_page(self, image):
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        background = cv2.GaussianBlur(gray, (0, 0), 21)
        normalized = cv2.divide(gray, background, scale=255)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(normalized)
        denoised = cv2.fastNlMeansDenoising(enhanced, None, 7, 7, 21)
        _, binary = cv2.threshold(denoised, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        blended = cv2.addWeighted(binary, 0.78, denoised, 0.22, 0)
        return Image.fromarray(blended).convert("RGB")

    def _process_image(self, path):
        if path in self.processed_cache:
            return self.processed_cache[path].copy()
        image = self._read_image_cv(path)
        if image is None:
            return None
        if image.shape[1] > image.shape[0]:
            image = cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
        processed = self._enhance_scanned_page(image)
        self.processed_cache[path] = processed.copy()
        return processed

    def on_select(self, _event=None):
        if cv2 is None or np is None:
            return
        cur = self.listbox.curselection()
        if not cur:
            return
        path = self.file_paths[cur[0]]
        try:
            self.status_label.config(text="미리보기 생성 중...")
            original = load_image_frame(path, 0)
            processed = self._process_image(path)
            self.original_photo = create_preview_photo(original, max_size=(380, 420), master=self.original_label)
            self.original_label.configure(image=self.original_photo, text="")
            if processed is not None:
                self.processed_photo = create_preview_photo(processed, max_size=(380, 420), master=self.processed_label)
                self.processed_label.configure(image=self.processed_photo, text="")
            self.status_label.config(text="미리보기 완료")
        except Exception as exc:
            self.status_label.config(text="미리보기 실패")
            show_error(self, "미리보기 실패", exc)

    def export_selected_pdf(self):
        if cv2 is None or np is None:
            return
        cur = self.listbox.curselection()
        if not cur:
            messagebox.showwarning("안내", "파일을 선택해 주세요.", parent=self)
            return
        path = self.file_paths[cur[0]]
        out_path = filedialog.asksaveasfilename(parent=self, defaultextension=".pdf", filetypes=[("PDF files", "*.pdf")], initialfile=os.path.splitext(os.path.basename(path))[0] + ".pdf")
        if not out_path:
            return
        try:
            processed = self._process_image(path)
            if processed is None:
                raise RuntimeError("이미지를 처리할 수 없습니다.")
            processed.save(out_path, "PDF", resolution=200.0)
            messagebox.showinfo("완료", f"저장되었습니다.\n{out_path}", parent=self)
        except Exception as exc:
            show_error(self, "PDF 저장 실패", exc)

    def export_merged_pdf(self):
        if cv2 is None or np is None:
            return
        if not self.file_paths:
            messagebox.showwarning("안내", "이미지를 추가해 주세요.", parent=self)
            return
        out_path = filedialog.asksaveasfilename(parent=self, defaultextension=".pdf", filetypes=[("PDF files", "*.pdf")], initialfile="scan_merged.pdf")
        if not out_path:
            return
        try:
            images = []
            for path in self.file_paths:
                processed = self._process_image(path)
                if processed is not None:
                    images.append(processed)
            if not images:
                raise RuntimeError("변환 가능한 이미지가 없습니다.")
            images[0].save(out_path, "PDF", save_all=True, append_images=images[1:], resolution=200.0)
            messagebox.showinfo("완료", f"저장되었습니다.\n{out_path}", parent=self)
        except Exception as exc:
            show_error(self, "병합 PDF 저장 실패", exc)


BaseRoot = TkinterDnD.Tk if TkinterDnD else tk.Tk


class UnifiedDocumentApp(BaseRoot):
    def __init__(self):
        super().__init__()
        apply_app_id()
        self.title(APP_TITLE)
        apply_window_icon(self)
        self.geometry("1280x860")
        self.minsize(1120, 720)
        self.option_add("*Font", "{Malgun Gothic} 10")
        configure_app_styles(self)
        self._build_ui()

    def _build_ui(self):
        root = ttk.Frame(self, style="App.TFrame", padding=10)
        root.pack(fill="both", expand=True)

        header = ttk.Frame(root, style="Header.TFrame", padding=(20, 18))
        header.pack(fill="x", pady=(0, 10))
        ttk.Label(header, text=APP_TITLE, style="HeaderText.TLabel", font=("Malgun Gothic", 18, "bold")).pack(anchor="w")
        ttk.Label(header, text=APP_SUBTITLE, style="HeaderSub.TLabel", font=("Malgun Gothic", 10)).pack(anchor="w", pady=(4, 0))

        notebook = ttk.Notebook(root)
        notebook.pack(fill="both", expand=True)

        notebook.add(MergeTab(notebook), text="PDF/이미지 병합")
        notebook.add(ImageToPdfTab(notebook), text="이미지 → PDF")
        notebook.add(PdfToImageTab(notebook), text="PDF → 이미지")
        notebook.add(ScanToPdfTab(notebook), text="이미지 스캔 보정")


def main():
    app = UnifiedDocumentApp()
    app.mainloop()


if __name__ == "__main__":
    main()
