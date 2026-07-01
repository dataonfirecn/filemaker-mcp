from io import BytesIO

import qrcode
import segno


def build_qr_payload(*, data: str | None, token: str | None, base_url: str) -> str:
    if data:
        return data
    if token:
        return f"{base_url.rstrip('/')}/{token}"
    raise ValueError("Either data or token is required")


def generate_png(
    *,
    payload: str,
    box_size: int,
    border: int,
    fill_color: str,
    back_color: str,
) -> bytes:
    qr = qrcode.QRCode(box_size=box_size, border=border)
    qr.add_data(payload)
    qr.make(fit=True)
    image = qr.make_image(fill_color=fill_color, back_color=back_color)
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def generate_svg(*, payload: str, border: int) -> bytes:
    qr = segno.make(payload)
    output = BytesIO()
    qr.save(output, kind="svg", border=border)
    return output.getvalue()
