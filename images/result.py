from dataclasses import dataclass
from typing import Optional


@dataclass
class CompressionResult:
    data: bytes
    filename: str
    format: str
    method: str
    original_size: int
    optimized_size: int
    target_size: Optional[int] = None
    quality: Optional[int] = None
    near_lossless_level: Optional[int] = None
    scale: Optional[float] = None
    original_width: Optional[int] = None
    original_height: Optional[int] = None
    optimized_width: Optional[int] = None  
    optimized_height: Optional[int] = None 
    dimension_capped: Optional[bool] = None

    def meets_target(self) -> bool:
        return self.target_size is None or self.optimized_size <= self.target_size

    def is_smaller_than_original(self) -> bool:
        return self.optimized_size <= self.original_size