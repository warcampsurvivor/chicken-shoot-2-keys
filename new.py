import sys
import random
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QDialog, QFileDialog,
    QProgressBar, QListWidget, QListWidgetItem, QTabWidget,
    QSplitter, QSizePolicy, QSpacerItem
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont, QIntValidator

alp = "23456789ABCDEFGHJKLMNPQRSTUWVXYZ"
MASK = 0x258410C103108904

CRC_TABLE = []
for i in range(256):
    c = i
    for _ in range(8):
        if c & 1: c = (c >> 1) ^ 0xA001
        else: c >>= 1
    CRC_TABLE.append(c)


def _calc_crc(data: int) -> int:
    crc = 0
    for b in [(data >> (8*i)) & 0xFF for i in range(8)]:
        crc = ((crc >> 8) ^ CRC_TABLE[(b ^ crc) & 0xFF]) & 0xFFFF
    return crc


def _build_G():
    crc_of_basis = []
    for bit in range(64):
        data = 1 << bit
        crc = 0
        for b in [(data >> (8*i)) & 0xFF for i in range(8)]:
            crc = ((crc >> 8) ^ CRC_TABLE[(b ^ crc) & 0xFF]) & 0xFFFF
        crc_of_basis.append(crc)
    C = [[(crc_of_basis[col] >> (15 - row)) & 1 for col in range(64)] for row in range(16)]
    mask_idx_of = {}
    mi = 0
    for i in range(64):
        if (MASK & (1 << i)) != 0:
            mask_idx_of[i] = mi; mi += 1
    G = [[0]*64 for _ in range(80)]
    for i in range(64):
        if i in mask_idx_of:
            mj = mask_idx_of[i]
            G[i] = list(C[15 - mj])
            G[64 + mj][i] = 1
        else:
            G[i][i] = 1
    return G

_G = _build_G()


def gen(data: int) -> str:
    crc = _calc_crc(data)
    bits = [0] * 80
    mask_bit_idx = 0
    for i in range(64):
        if (MASK & (1 << i)) != 0:
            bits[i] = (crc >> (15 - mask_bit_idx)) & 1
            bits[64 + mask_bit_idx] = (data >> i) & 1
            mask_bit_idx += 1
        else:
            bits[i] = (data >> i) & 1
    key_chars = []
    for i in range(16):
        val = 0
        for b in range(5): val |= bits[i*5+b] << b
        key_chars.append(alp[val])
    key = "".join(key_chars)
    return f"{key[0:4]}-{key[4:8]}-{key[8:12]}-{key[12:16]}"


def verify(key: str) -> bool:
    stripped = key.replace("-","").upper()
    if len(stripped) != 16: return False
    bits = []
    for ch in stripped:
        if ch not in alp: return False
        val = alp.index(ch)
        bits.extend([(val>>b)&1 for b in range(5)])
    payload, extracted_crc, mask_bit_idx = 0, 0, 0
    for i in range(64):
        if (MASK & (1 << i)) != 0:
            extracted_crc |= (bits[i] << (15 - mask_bit_idx))
            payload |= (bits[64 + mask_bit_idx] << i)
            mask_bit_idx += 1
        else:
            payload |= (bits[i] << i)
    return _calc_crc(payload) == extracted_crc


def _row(bit_idx):
    return list(_G[bit_idx])


def _csys(vanity, pos):
    A, b = [], []
    for i, ch in enumerate(vanity):
        val = alp.index(ch)
        for bt in range(5):
            A.append(_row((pos+i)*5+bt))
            b.append((val>>bt)&1)
    return A, b


def _gauss(A, b):
    n_rows, n_cols = len(A), 64
    M = [list(row)+[bi] for row, bi in zip(A, b)]
    pivots = []; pivot_row = 0
    for col in range(n_cols):
        found = next((r for r in range(pivot_row, n_rows) if M[r][col]), -1)
        if found < 0: continue
        M[pivot_row], M[found] = M[found], M[pivot_row]
        pivots.append(col)
        for r in range(n_rows):
            if r != pivot_row and M[r][col]:
                M[r] = [M[r][j]^M[pivot_row][j] for j in range(n_cols+1)]
        pivot_row += 1
    pivot_set = set(pivots)
    if any(M[r][n_cols] for r in range(pivot_row, n_rows)): return pivots, [], M, False
    free = [c for c in range(n_cols) if c not in pivot_set]
    return pivots, free, M, True


def _vanity(vanity, count=1):
    vanity = vanity.upper()
    max_pos = 16 - len(vanity)
    if max_pos < 0: return
    for ch in vanity:
        if ch not in alp: raise ValueError(f"bad char '{ch}'")

    cache = {}
    valid_positions = []
    for pos in range(max_pos+1):
        A, b = _csys(vanity, pos)
        pivots, free, M, ok = _gauss(A, b)
        if ok: cache[pos] = (pivots, free, M); valid_positions.append(pos)
    if not valid_positions: return

    generated = 0; attempts = 0
    while generated < count and attempts < count*1000:
        attempts += 1
        pivots, free, M = cache[random.choice(valid_positions)]
        data_vec = [0]*64
        for fc in free: data_vec[fc] = random.randint(0,1)
        for i, pc in enumerate(pivots):
            rhs = M[i][64]
            for fc in free: rhs ^= M[i][fc]*data_vec[fc]
            data_vec[pc] = rhs&1
        key = gen(sum(b<<i for i,b in enumerate(data_vec)))
        if vanity in key.replace("-",""):
            yield key; generated += 1


class copy(QLineEdit):
    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        txt = self.text()
        if txt and txt != "PRESS GENERATE":
            QApplication.clipboard().setText(txt)
            w = self.window()
            if hasattr(w, "update_log"): w.update_log("Key copied to clipboard!")


class BulkWorker(QThread):
    progress = Signal(int, int)
    finished = Signal(list)
    error    = Signal(str)

    def __init__(self, count, vanity):
        super().__init__()
        self.count = count; self.vanity = vanity.upper(); self._is_running = True

    def run(self):
        if self.vanity:
            for ch in self.vanity:
                if ch not in alp:
                    self.error.emit(f"Char '{ch}' impossible! Allowed: {alp}"); return
        keys = []
        if self.vanity:
            try:
                for key in _vanity(self.vanity, self.count):
                    if not self._is_running: break
                    keys.append(key); self.progress.emit(len(keys), self.count)
            except ValueError as e:
                self.error.emit(str(e)); return
        else:
            while len(keys) < self.count and self._is_running:
                keys.append(gen(random.getrandbits(64)))
                if len(keys) % max(1, self.count//100) == 0 or len(keys) == self.count:
                    self.progress.emit(len(keys), self.count)
        if self._is_running: self.finished.emit(keys)

    def stop(self): self._is_running = False


class VanityWorker(QThread):
    key_found = Signal(str)
    finished  = Signal(int)
    error     = Signal(str)

    def __init__(self, vanity, count):
        super().__init__()
        self.vanity = vanity.upper(); self.count = count; self._is_running = True

    def run(self):
        for ch in self.vanity:
            if ch not in alp:
                self.error.emit(f"Char '{ch}' impossible! Allowed: {alp}"); return
        found = 0
        try:
            for key in _vanity(self.vanity, self.count):
                if not self._is_running: break
                self.key_found.emit(key); found += 1
        except ValueError as e:
            self.error.emit(str(e)); return
        self.finished.emit(found)

    def stop(self): self._is_running = False


_SS = """
    QDialog, QWidget  { background-color: #5c5c5c; }
    QTabWidget::pane  { border: 2px solid #2a2a2a; background: #5c5c5c; }
    QTabBar::tab      { background: #484848; color: #cccccc; padding: 4px 12px;
                        border: 1px solid #2a2a2a; border-bottom: none; }
    QTabBar::tab:selected { background: #5c5c5c; color: #ffffff; font-weight: bold; }
    QLabel            { color: #ffffff; border: none; font-weight: bold; }
    QLineEdit         { background-color: #ffffff; color: #000000;
                        border: 2px inset #999999; font-weight: bold; }
    QListWidget       { background-color: #ffffff; color: #000000;
                        border: 2px inset #999999; font-weight: bold; }
    QPushButton       { background-color: #e0e0e0; color: #000000;
                        border: 2px outset #ffffff; padding: 4px; min-width: 60px; }
    QPushButton:pressed   { border: 2px inset #555555; }
    QPushButton:disabled  { background-color: #888888; color: #dddddd;
                            border: 2px outset #aaaaaa; }
    QProgressBar      { border: 2px inset #999999; background-color: #ffffff;
                        text-align: center; color: black; font-weight: bold; }
    QProgressBar::chunk { background-color: #4caf50; }
"""


class BulkTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.worker = None; self.file_path = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8,8,8,8); layout.setSpacing(5)

        layout.addWidget(QLabel("Number of Keys:"))
        self.txt_num = QLineEdit("100")
        self.txt_num.setValidator(QIntValidator(1, 1_000_000, self))
        layout.addWidget(self.txt_num)

        layout.addWidget(QLabel("Vanity Filter (optional):"))
        self.txt_vanity = QLineEdit()
        self.txt_vanity.setPlaceholderText("e.g. BASS")
        layout.addWidget(self.txt_vanity)

        self.lbl_hint = QLabel("")
        self.lbl_hint.setStyleSheet("color: #aaffaa; font-weight: normal;")
        layout.addWidget(self.lbl_hint)

        self.lbl_status = QLabel("Ready")
        layout.addWidget(self.lbl_status)

        self.progress = QProgressBar()
        layout.addWidget(self.progress)

        btn_layout = QHBoxLayout()
        self.btn_pick = QPushButton("Choose File…"); self.btn_pick.clicked.connect(self._pick_file)
        self.btn_gen  = QPushButton("Generate & Save"); self.btn_gen.clicked.connect(self._start); self.btn_gen.setEnabled(False)
        self.btn_stop = QPushButton("Stop"); self.btn_stop.clicked.connect(self._stop); self.btn_stop.setEnabled(False)
        for b in (self.btn_pick, self.btn_gen, self.btn_stop): btn_layout.addWidget(b)
        layout.addLayout(btn_layout)

        self.lbl_file = QLabel("No file selected")
        self.lbl_file.setStyleSheet("color: #aaaaaa; font-weight: normal;")
        layout.addWidget(self.lbl_file)

    def _update_hint(self, text):
        t = text.upper().strip()
        if not t: self.lbl_hint.setText(""); return
        bad = [c for c in t if c not in alp]
        if bad:
            self.lbl_hint.setText(f"⚠ invalid: {''.join(bad)}")
            self.lbl_hint.setStyleSheet("color: #ffaaaa; font-weight: normal;")


    def _pick_file(self):
        import os, random as _r
        base = "keys"
        default = f"{base}_{_r.randint(0,9999):04d}.txt"
        while os.path.exists(default):
            default = f"{base}_{_r.randint(0,9999):04d}.txt"
        path, _ = QFileDialog.getSaveFileName(self, "Save Keys", default, "Text Files (*.txt)")
        if path:
            self.file_path = path
            self.lbl_file.setText(os.path.basename(path))
            self.lbl_file.setStyleSheet("color: #ffffff; font-weight: normal;")
            self.btn_gen.setEnabled(True)

    def _start(self):
        num_text = self.txt_num.text()
        if not num_text.isdigit() or int(num_text) <= 0:
            self.lbl_status.setText("Enter a valid count."); return
        vanity = self.txt_vanity.text().upper().strip()
        if vanity and any(c not in alp for c in vanity):
            self.lbl_status.setText("Invalid vanity char."); return
        count = int(num_text)
        self.progress.setMaximum(count); self.progress.setValue(0)
        self.lbl_status.setText("Generating…")
        self.btn_gen.setEnabled(False); self.btn_pick.setEnabled(False); self.btn_stop.setEnabled(True)
        self.worker = BulkWorker(count, vanity)
        self.worker.progress.connect(lambda c,t: (self.progress.setValue(c), self.lbl_status.setText(f"{c} / {t}")))
        self.worker.finished.connect(self._on_finished)
        self.worker.error.connect(self._on_error)
        self.worker.start()

    def _stop(self):
        if self.worker and self.worker.isRunning(): self.worker.stop(); self.worker.wait()
        self._reset_buttons(); self.lbl_status.setText("Stopped.")

    def _on_finished(self, keys):
        self._reset_buttons()
        try:
            with open(self.file_path, "w") as f: f.write("\n".join(keys)+"\n")
            self.lbl_status.setText(f"✓ Saved {len(keys)} keys.")
        except Exception as e:
            self.lbl_status.setText(f"Save error: {e}")

    def _on_error(self, msg): self._reset_buttons(); self.lbl_status.setText(f"Error: {msg}")

    def _reset_buttons(self):
        self.btn_gen.setEnabled(bool(self.file_path))
        self.btn_pick.setEnabled(True); self.btn_stop.setEnabled(False)

    def cleanup(self):
        if self.worker and self.worker.isRunning(): self.worker.stop(); self.worker.wait()


class VanityTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.worker = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8,8,8,8); layout.setSpacing(5)

        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("Vanity String:"))
        self.txt_vanity = QLineEdit()
        self.txt_vanity.setPlaceholderText("e.g. DEAD")
        self.txt_vanity.setMaxLength(11)
        top_row.addWidget(self.txt_vanity)
        layout.addLayout(top_row)

        count_row = QHBoxLayout()
        count_row.addWidget(QLabel("Count:"))
        self.txt_count = QLineEdit("10")
        self.txt_count.setValidator(QIntValidator(1, 10_000, self))
        self.txt_count.setFixedWidth(60)
        count_row.addWidget(self.txt_count); count_row.addStretch()
        layout.addLayout(count_row)

        self.lst = QListWidget()
        self.lst.setSelectionMode(QListWidget.ExtendedSelection)
        self.lst.itemClicked.connect(self._copy_item)
        self.lst.setToolTip("Click to copy. Multi-select + Copy Selected for batch.")
        layout.addWidget(self.lst)

        self.lbl_status = QLabel("Enter a vanity string and press Generate")
        self.lbl_status.setStyleSheet("font-weight: normal; color: #cccccc;")
        layout.addWidget(self.lbl_status)

        btn_layout = QHBoxLayout()
        self.btn_gen    = QPushButton("Generate");  self.btn_gen.clicked.connect(self._start)
        self.btn_stop   = QPushButton("Stop");      self.btn_stop.clicked.connect(self._stop);  self.btn_stop.setEnabled(False)
        self.btn_export = QPushButton("Export…");   self.btn_export.clicked.connect(self._export)
        for b in (self.btn_gen, self.btn_stop, self.btn_export):
            btn_layout.addWidget(b)
        layout.addLayout(btn_layout)

    def _start(self):
        vanity = self.txt_vanity.text().upper().strip()
        if not vanity: self.lbl_status.setText("Enter a vanity string."); return
        if any(c not in alp for c in vanity): self.lbl_status.setText("Invalid char."); return
        num_text = self.txt_count.text()
        count = int(num_text) if num_text.isdigit() and int(num_text) > 0 else 10
        self.lst.clear()
        self.btn_gen.setEnabled(False); self.btn_stop.setEnabled(True)
        self.lbl_status.setText(f"Solving '{vanity}'…")
        self.worker = VanityWorker(vanity, count)
        self.worker.key_found.connect(self._add_key)
        self.worker.finished.connect(self._on_finished)
        self.worker.error.connect(self._on_error)
        self.worker.start()

    def _stop(self):
        if self.worker and self.worker.isRunning(): self.worker.stop(); self.worker.wait()
        self._reset_buttons(); self.lbl_status.setText(f"Stopped. {self.lst.count()} keys.")

    def _add_key(self, key):
        item = QListWidgetItem(key); item.setFont(QFont("Courier New", 9))
        self.lst.addItem(item); self.lst.scrollToBottom()
        self.lbl_status.setText(f"{self.lst.count()} key(s)…")

    def _on_finished(self, count): self._reset_buttons(); self.lbl_status.setText(f"Done — {count} key(s).")
    def _on_error(self, msg): self._reset_buttons(); self.lbl_status.setText(f"Error: {msg}")
    def _reset_buttons(self): self.btn_gen.setEnabled(True); self.btn_stop.setEnabled(False)

    def _copy_item(self, item):
        QApplication.clipboard().setText(item.text())
        self.lbl_status.setText(f"Copied: {item.text()}")

    def _export(self):
        if not self.lst.count(): self.lbl_status.setText("Nothing to export."); return
        file_path, _ = QFileDialog.getSaveFileName(self, "Export", "vanity_keys.txt", "Text Files (*.txt)")
        if not file_path: return
        keys = [self.lst.item(i).text() for i in range(self.lst.count())]
        with open(file_path, "w") as f: f.write("\n".join(keys)+"\n")
        self.lbl_status.setText(f"Exported {len(keys)} keys.")


    def cleanup(self):
        if self.worker and self.worker.isRunning(): self.worker.stop(); self.worker.wait()


class BulkDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setFixedSize(420, 380)
        self.setFont(QFont("Tahoma", 8))
        self.setStyleSheet(_SS)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6,6,6,6); layout.setSpacing(4)

        title = QLabel("  Key Generator — Bulk / Vanity")
        title.setStyleSheet("font-weight: bold; font-size: 9pt; color: #ffffff;")
        layout.addWidget(title)

        self.tabs = QTabWidget()
        self.tab_bulk   = BulkTab(self); self.tab_vanity = VanityTab(self)
        self.tabs.addTab(self.tab_bulk, "Bulk Export")
        self.tabs.addTab(self.tab_vanity, "Vanity")
        layout.addWidget(self.tabs)

        btn_layout = QHBoxLayout(); btn_layout.addStretch()
        btn_close = QPushButton("Close"); btn_close.clicked.connect(self.close_dialog)
        btn_layout.addWidget(btn_close); layout.addLayout(btn_layout)

    def close_dialog(self):
        self.tab_bulk.cleanup(); self.tab_vanity.cleanup(); self.close()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_pos)


class Keygen(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setFixedSize(360, 170)
        self.setFont(QFont("Tahoma", 8))
        self.setStyleSheet("""
            QWidget     { background-color: #5c5c5c; border: 2px solid #2a2a2a; }
            QLabel      { color: #ffffff; border: none; font-weight: bold; }
            QLineEdit   { background-color: #ffffff; color: #000000;
                          border: 2px inset #999999; font-weight: bold; }
            QPushButton { background-color: #e0e0e0; color: #000000;
                          border: 2px outset #ffffff; padding: 4px; min-width: 60px; }
            QPushButton:pressed { border: 2px inset #555555; }
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10,10,10,10); layout.setSpacing(5)

        hdr = QHBoxLayout()
        lbl_title = QLabel("Key Generator"); lbl_title.setStyleSheet("font-size: 8pt;")
        hdr.addWidget(lbl_title); hdr.addStretch(); layout.addLayout(hdr)

        layout.addWidget(QLabel("CD-Key (click to copy):"))
        self.txt_key = copy()
        self.txt_key.setReadOnly(True); self.txt_key.setAlignment(Qt.AlignCenter)
        self.txt_key.setText("PRESS GENERATE")
        self.txt_key.setFont(QFont("Courier New", 10, QFont.Bold))
        layout.addWidget(self.txt_key)

        layout.addWidget(QLabel("Status:"))
        self.txt_log = QLineEdit("Ready")
        self.txt_log.setReadOnly(True)
        self.txt_log.setStyleSheet("background-color: #dcdcdc; border: 1px solid #999;")
        layout.addWidget(self.txt_log)

        btn_layout = QHBoxLayout()
        self.btn_gen  = QPushButton("Generate");       self.btn_gen.clicked.connect(self.on_generate)
        self.btn_bulk = QPushButton("Bulk / Vanity…"); self.btn_bulk.clicked.connect(self.open_bulk)
        self.btn_exit = QPushButton("Exit");           self.btn_exit.clicked.connect(self.close)
        for b in (self.btn_gen, self.btn_bulk, self.btn_exit): btn_layout.addWidget(b)
        layout.addLayout(btn_layout)

    def update_log(self, msg): self.txt_log.setText(msg)

    def on_generate(self):
        new_key = gen(random.getrandbits(64))
        self.txt_key.setText(new_key); QApplication.clipboard().setText(new_key)
        self.update_log("Key generated and copied!")

    def open_bulk(self):
        self.bulk_dialog = BulkDialog(self); self.bulk_dialog.show()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_pos)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = Keygen()
    window.show()
    sys.exit(app.exec())
