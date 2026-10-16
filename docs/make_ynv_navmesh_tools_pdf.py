from pathlib import Path
import re
import textwrap


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "YNV_NavMesh_Tools_Guide.md"
OUTPUT = ROOT / "YNV_NavMesh_Tools_Guide.pdf"


PAGE_WIDTH = 595
PAGE_HEIGHT = 842
LEFT = 54
TOP = 790
LINE_HEIGHT = 14
BODY_SIZE = 10
TITLE_SIZE = 18
H1_SIZE = 15
H2_SIZE = 12
MONO_SIZE = 9


def pdf_escape(text):
    return (
        text.replace("\\", "\\\\")
        .replace("(", "\\(")
        .replace(")", "\\)")
    )


def normalize(text):
    replacements = {
        "ä": "ae",
        "ö": "oe",
        "ü": "ue",
        "Ä": "Ae",
        "Ö": "Oe",
        "Ü": "Ue",
        "ß": "ss",
        "©": "(c)",
        "–": "-",
        "—": "-",
        "“": '"',
        "”": '"',
        "’": "'",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def strip_markdown(line):
    line = line.strip()
    line = re.sub(r"`([^`]+)`", r"\1", line)
    line = re.sub(r"\*\*([^*]+)\*\*", r"\1", line)
    line = re.sub(r"\*([^*]+)\*", r"\1", line)
    return normalize(line)


def parse_markdown(text):
    blocks = []
    in_code = False
    for raw in text.splitlines():
        line = raw.rstrip()
        if line.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            blocks.append(("code", normalize(line)))
            continue
        if not line.strip():
            blocks.append(("blank", ""))
        elif line.startswith("# "):
            blocks.append(("title", strip_markdown(line[2:])))
        elif line.startswith("## "):
            blocks.append(("h1", strip_markdown(line[3:])))
        elif line.startswith("### "):
            blocks.append(("h2", strip_markdown(line[4:])))
        elif line.startswith("- "):
            blocks.append(("bullet", strip_markdown(line[2:])))
        elif re.match(r"\d+\. ", line):
            blocks.append(("number", strip_markdown(line)))
        else:
            blocks.append(("para", strip_markdown(line)))
    return blocks


class PdfBuilder:
    def __init__(self):
        self.pages = []
        self.current = []
        self.y = TOP
        self.page_no = 0
        self.new_page()

    def new_page(self):
        if self.current:
            self.pages.append(self.current)
        self.page_no += 1
        self.current = []
        self.y = TOP
        self.text(LEFT, 28, 8, "GTANAVMESH Edit - User Guide", font="F1")
        self.text(PAGE_WIDTH - 110, 28, 8, f"Page {self.page_no}", font="F3")

    def ensure(self, lines=1):
        if self.y - lines * LINE_HEIGHT < 54:
            self.new_page()

    def text(self, x, y, size, text, font="F1"):
        escaped = pdf_escape(text)
        self.current.append(f"BT /{font} {size} Tf {x} {y} Td ({escaped}) Tj ET")

    def add_wrapped(self, text, size=BODY_SIZE, indent=0, bullet=None, font="F1", width=86):
        prefix_width = 4 if bullet else 0
        wrap_width = max(28, width - indent - prefix_width)
        lines = textwrap.wrap(text, width=wrap_width) or [""]
        self.ensure(len(lines))
        for i, line in enumerate(lines):
            x = LEFT + indent * 4
            if bullet and i == 0:
                self.text(x, self.y, size, bullet, font=font)
                x += 16
            elif bullet:
                x += 16
            self.text(x, self.y, size, line, font=font)
            self.y -= LINE_HEIGHT

    def add_block(self, kind, text):
        if kind == "blank":
            self.y -= 5
            if self.y < 70:
                self.new_page()
            return
        if kind == "title":
            self.ensure(3)
            self.text(LEFT, self.y, TITLE_SIZE, text, font="F2")
            self.y -= 26
            return
        if kind == "h1":
            self.y -= 6
            self.ensure(2)
            self.text(LEFT, self.y, H1_SIZE, text, font="F2")
            self.y -= 22
            return
        if kind == "h2":
            self.y -= 3
            self.ensure(2)
            self.text(LEFT, self.y, H2_SIZE, text, font="F2")
            self.y -= 18
            return
        if kind == "bullet":
            self.add_wrapped(text, bullet="-")
            return
        if kind == "number":
            m = re.match(r"(\d+\.)(.*)", text)
            if m:
                self.add_wrapped(m.group(2).strip(), bullet=m.group(1))
            else:
                self.add_wrapped(text)
            return
        if kind == "code":
            self.add_wrapped(text, size=MONO_SIZE, font="F3", width=78)
            return
        self.add_wrapped(text)

    def finish(self):
        if self.current:
            self.pages.append(self.current)
            self.current = []

        objects = []
        font1 = "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
        font2 = "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>"
        font3 = "<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>"
        objects.extend([font1, font2, font3])

        page_object_ids = []
        content_object_ids = []
        for page in self.pages:
            stream = "\n".join(page).encode("latin-1", errors="replace")
            content = f"<< /Length {len(stream)} >>\nstream\n".encode("latin-1") + stream + b"\nendstream"
            objects.append(content)
            content_object_ids.append(len(objects))
            page_object_ids.append(len(objects) + 1)
            objects.append("")

        pages_id = len(objects) + 1
        catalog_id = len(objects) + 2
        for idx, page_id in enumerate(page_object_ids):
            content_id = content_object_ids[idx]
            objects[page_id - 1] = (
                f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 {PAGE_WIDTH} {PAGE_HEIGHT}] "
                f"/Resources << /Font << /F1 1 0 R /F2 2 0 R /F3 3 0 R >> >> "
                f"/Contents {content_id} 0 R >>"
            )

        kids = " ".join(f"{pid} 0 R" for pid in page_object_ids)
        objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(page_object_ids)} >>")
        objects.append(f"<< /Type /Catalog /Pages {pages_id} 0 R >>")

        data = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = [0]
        for i, obj in enumerate(objects, start=1):
            offsets.append(len(data))
            data.extend(f"{i} 0 obj\n".encode("latin-1"))
            if isinstance(obj, bytes):
                data.extend(obj)
            else:
                data.extend(obj.encode("latin-1", errors="replace"))
            data.extend(b"\nendobj\n")

        xref = len(data)
        data.extend(f"xref\n0 {len(objects)+1}\n".encode("latin-1"))
        data.extend(b"0000000000 65535 f \n")
        for offset in offsets[1:]:
            data.extend(f"{offset:010d} 00000 n \n".encode("latin-1"))
        data.extend(
            f"trailer\n<< /Size {len(objects)+1} /Root {catalog_id} 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode("latin-1")
        )
        OUTPUT.write_bytes(data)


def main():
    blocks = parse_markdown(SOURCE.read_text(encoding="utf-8"))
    pdf = PdfBuilder()
    for kind, text in blocks:
        pdf.add_block(kind, text)
    pdf.finish()
    print(OUTPUT)


if __name__ == "__main__":
    main()
