"""将 neonize 下发的 QR 字符串渲染为 QImage（对齐旧版 segno 逻辑）。"""
from __future__ import annotations

import io

from PySide6.QtGui import QImage


def qr_payload_to_qimage(data: bytes | str, *, scale: int = 8) -> QImage:
    """neonize 回调是 UTF-8 配对串，不是 PNG；需用 segno 画成图。"""
    import segno

    if isinstance(data, bytes):
        # 先尝试当图片；失败再当配对串
        image = QImage.fromData(data)
        if not image.isNull():
            return image
        payload = data.decode("utf-8", errors="ignore").strip()
    else:
        payload = str(data or "").strip()
    if not payload:
        return QImage()
    qr = segno.make_qr(payload)
    buf = io.BytesIO()
    qr.save(buf, kind="png", scale=max(2, int(scale)), border=2)
    buf.seek(0)
    image = QImage.fromData(buf.getvalue(), "PNG")
    return image if image is not None else QImage()
