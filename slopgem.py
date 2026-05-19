import sys
import random
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QLineEdit, QPushButton, QFrame
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

MASK = 0x258410C103108904
ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUWVXYZ"
CRC_TABLE = []
for i in range(256):
    c = i
    for _ in range(8):
        if c & 1: c = (c >> 1) ^ 0xA001
        else: c >>= 1
    CRC_TABLE.append(c)

def calculate_crc(data_bytes):
    crc = 0x0000
    for b in data_bytes:
        index = (b ^ (crc & 0xFF))
        crc = ((crc >> 8) ^ CRC_TABLE[index]) & 0xFFFF
    return crc

def generate_key(data_64bit):
    data_bytes = [(data_64bit >> (8 * i)) & 0xFF for i in range(8)]
    expected_crc = calculate_crc(data_bytes)
    bits = [0] * 80
    mask_bit_idx = 0
    for i in range(64):
        if (MASK & (1 << i)) != 0:
            bits[i] = (expected_crc >> (15 - mask_bit_idx)) & 1
            bits[64 + mask_bit_idx] = (data_64bit >> i) & 1
            mask_bit_idx += 1
        else:
            bits[i] = (data_64bit >> i) & 1
    key_chars = []
    for i in range(16):
        val = 0
        for b in range(5):
            val |= (bits[i * 5 + b] << b)
        key_chars.append(ALPHABET[val])
    key = "".join(key_chars)
    return f"{key[0:4]}-{key[4:8]}-{key[8:12]}-{key[12:16]}"

class CopyableLineEdit(QLineEdit):
    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        if self.text() and self.text() != "PRESS GENERATE":
            QApplication.clipboard().setText(self.text())
            self.window().update_log("Key copied to clipboard!")

class Keygen(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setFixedSize(360, 160)
        self.setFont(QFont("Tahoma", 8))
        
        self.setStyleSheet("""
            QWidget { background-color: #5c5c5c; border: 2px solid #2a2a2a; }
            QLabel { color: #ffffff; border: none; font-weight: bold; }
            QLineEdit { 
                background-color: #ffffff; color: #000000; 
                border: 2px inset #999999; font-weight: bold; 
            }
            QPushButton {
                background-color: #e0e0e0; color: #000000;
                border: 2px outset #ffffff; padding: 4px; min-width: 60px;
            }
            QPushButton:pressed { border: 2px inset #555555; }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(5)

        layout.addWidget(QLabel("CD-Key (Click to Copy):"))
        self.txt_key = CopyableLineEdit()
        self.txt_key.setReadOnly(True)
        self.txt_key.setAlignment(Qt.AlignCenter)
        self.txt_key.setText("PRESS GENERATE")
        layout.addWidget(self.txt_key)

        layout.addWidget(QLabel("Status:"))
        self.txt_log = QLineEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setStyleSheet("background-color: #dcdcdc; border: 1px solid #999;")
        self.txt_log.setText("Ready")
        layout.addWidget(self.txt_log)

        btn_layout = QHBoxLayout()
        self.btn_gen = QPushButton("Generate")
        self.btn_gen.clicked.connect(self.on_generate)
        self.btn_about = QPushButton("About")
        self.btn_about.clicked.connect(lambda: self.update_log("by rygo"))
        self.btn_exit = QPushButton("Exit")
        self.btn_exit.clicked.connect(self.close)
        
        btn_layout.addWidget(self.btn_gen)
        btn_layout.addWidget(self.btn_about)
        btn_layout.addWidget(self.btn_exit)
        layout.addLayout(btn_layout)

    def update_log(self, msg):
        self.txt_log.setText(msg)

    def on_generate(self):
        new_key = generate_key(random.getrandbits(64))
        self.txt_key.setText(new_key)
        self.update_log("Key generated.")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_pos)
            event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = Keygen()
    window.show()
    sys.exit(app.exec())