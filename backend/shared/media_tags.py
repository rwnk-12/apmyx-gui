import datetime
from dataclasses import dataclass


@dataclass
class MediaTags:
    album: str = None
    album_artist: str = None
    album_id: int = None
    artist: str = None
    artist_id: int = None
    composer: str = None
    copyright: str = None
    date: datetime.date | str = None
    disc: int = None
    disc_total: int = None
    genre: str = None
    lyrics: str = None
    rating: int = None
    title: str = None
    title_id: int = None
    track: int = None
    track_total: int = None

    def as_mp4_tags(self, date_format: str = None) -> dict:
        disc_mp4 = [
            self.disc if self.disc is not None else 0,
            self.disc_total if self.disc_total is not None else 0,
        ]
        if disc_mp4[0] == 0 and disc_mp4[1] == 0:
            disc_mp4 = None

        track_mp4 = [
            self.track if self.track is not None else 0,
            self.track_total if self.track_total is not None else 0,
        ]
        if track_mp4[0] == 0 and track_mp4[1] == 0:
            track_mp4 = None

        if isinstance(self.date, datetime.date):
            if date_format is None:
                date_mp4 = self.date.isoformat()
            else:
                date_mp4 = self.date.strftime(date_format)
        elif isinstance(self.date, str):
            date_mp4 = self.date
        else:
            date_mp4 = None

        mp4_tags = {
            "\xa9alb": self.album,
            "aART": self.album_artist,
            "plID": self.album_id,
            "\xa9ART": self.artist,
            "atID": self.artist_id,
            "\xa9wrt": self.composer,
            "cprt": self.copyright,
            "\xa9day": date_mp4,
            "disk": disc_mp4,
            "\xa9gen": self.genre,
            "\xa9lyr": self.lyrics,
            "rtng": int(self.rating) if self.rating is not None else None,
            "\xa9nam": self.title,
            "cnID": self.title_id,
            "trkn": track_mp4,
        }

        return {k: [v] for k, v in mp4_tags.items() if v is not None}
