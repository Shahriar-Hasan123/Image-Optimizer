TARGET_SIZES = {
    'regular': 500 * 1024,
    'hero': 800 * 1024,
    'thumbnail': 50 * 1024,
    'logo': 100 * 1024,
}


RESPONSIVE_VARIANT_WIDTHS = {
    'thumbnail': {'mobile': 150,  'laptop': 300,  'desktop': 400},
    'logo':      {'mobile': 120,  'laptop': 200,  'desktop': 300},
    'regular':   {'mobile': 480,  'laptop': 1366, 'desktop': 1920},
    'hero':      {'mobile': 480,  'laptop': 1600, 'desktop': 1920},
}

DIMENSION_CONSTRAINTS = {
    'thumbnail': {'min_w': 50,   'min_h': 50,   'max_w': 800,   'max_h': 800},
    'logo':      {'min_w': 50,   'min_h': 50,   'max_w': 1000,  'max_h': 1000},
    'regular':   {'min_w': 200,  'min_h': 200,  'max_w': 4000,  'max_h': 4000},
    'hero':      {'min_w': 1200, 'min_h': 400,  'max_w': 6000,  'max_h': 4000},
}

RASTER_FORMATS = {'JPEG', 'PNG', 'WEBP', 'AVIF'}
SKIP_FORMATS = {'GIF', 'SVG'}          # returned unchanged, no compression attempted
ALREADY_LOSSY_SOURCE = {'JPEG', 'AVIF'}

MAX_IMAGE_PIXELS = 40_000_000          # ~40MP, checked per-call — NOT a global Pillow mutation
MAX_UPLOAD_BYTES = 20 * 1024 * 1024

QUALITY_HIGH_FLOOR = 75
QUALITY_FLOOR_SOFT = 40    # preferred floor — quality below this only used as last resort
QUALITY_FLOOR_HARD = 10    # absolute floor for the forced-fit guarantee step
NEAR_LOSSLESS_LEVELS = (95, 90, 85, 80, 75)
RESIZE_SCALE_STEPS = (0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1)
FORCED_FIT_SCALE = 0.1     # only reached if every prior rung fails
