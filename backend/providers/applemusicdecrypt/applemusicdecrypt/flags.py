from dataclasses import dataclass

from applemusicdecrypt.services import it

from applemusicdecrypt.config import Config


@dataclass
class Flags:
    force_save: bool = False
    include_participate_in_works: bool = False
    language: str = it(Config).region.language
