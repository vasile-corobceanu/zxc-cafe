from io import BytesIO

import qrcode
from qrcode.image.pil import PilImage


def generate_qr_code(bot_username, user_id):
    link = f"https://t.me/{bot_username}?start=user_id_{user_id}"
    qr = qrcode.QRCode(
        version=1,
        box_size=10,
        border=4,
    )
    qr.add_data(link)
    qr.make(fit=True)
    img = qr.make_image(fill='black', back_color='white', image_factory=PilImage)
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    buffer.name = 'qr_code.png'
    buffer.seek(0)
    return buffer
