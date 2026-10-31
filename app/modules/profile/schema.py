from enum import Enum
from pydantic import EmailStr,Field

from pydantic import BaseModel


class UserRelationship(str, Enum):
    single = "Célibataire"
    in_couple = "En couple"
    married = "Marié(e)"
    divorced = "Divorcé(e)"
    widowed = "Veuf/Veuve"


class UpdateProfile(BaseModel):
    first_name: str | None = None
    last_name: str | None = None

class UpdateProfileResponse(BaseModel):
    model_config = {"from_attributes":True}
    first_name : str|None
    last_name : str|None
    profile_pictures : str|None

class UpdateUserMail(BaseModel):
    email : EmailStr|None = None
    
    
