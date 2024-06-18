
from typing import Optional
from pydantic import BaseModel, field_validator, model_validator


class ProcessLogConfig(BaseModel):
    rotation_enabled: bool = True
    rotation_when: str = 'midnight'
    rotation_interval: Optional[int] = None
    backup_count : int = 30
    gzip_enabled: bool = True

    # Custom validator here
    @field_validator('rotation_interval', mode='before')
    def allow_none(cls, v):
        if v is None or v == '':
             return None
        else:
            return v