"""Stable product image bindings; list order never determines the main image."""
import re

MAIN_IMAGE_FIELD = 'image_main'
LEGACY_MAIN_IMAGE_FIELD = '檔案 1 | 容器'


def canonical_container_field(name):
    return MAIN_IMAGE_FIELD if name == LEGACY_MAIN_IMAGE_FIELD else name


def product_image_field(slot):
    if not isinstance(slot, int) or not 1 <= slot <= 20:
        raise ValueError('Invalid product image slot')
    return MAIN_IMAGE_FIELD if slot == 1 else f'檔案 {slot} | 容器'


def product_image_slot(name):
    if canonical_container_field(name) == MAIN_IMAGE_FIELD:
        return 1
    match = re.fullmatch(r'檔案\s+(\d+)\s+\|\s+容器', name)
    return int(match.group(1)) if match else None


def canonical_assets(assets):
    return [{**asset, 'field': canonical_container_field(asset['field'])} for asset in assets]
