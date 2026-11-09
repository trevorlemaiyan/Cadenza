"""
SQLAlchemy models for Cadenza.

Tables
------
Track   – curated track library with audio-feature vectors (the recommendation corpus)
User    – Spotify-authenticated users (migrated from MongoDB)
Message – persisted chat messages (optional history)
"""
from datetime import datetime

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class Track(db.Model):
    """
    One row per song in our curated library.

    Audio features are normalised to [0, 1].  tempo is stored raw (BPM) but
    normalised to [0, 1] at query time (÷ 250) inside recommender.py.
    """

    __tablename__ = "tracks"

    id = db.Column(db.Integer, primary_key=True)
    spotify_id = db.Column(db.String(64), unique=True, nullable=False, index=True)
    name = db.Column(db.String(256), nullable=False)
    artist = db.Column(db.String(256), nullable=False)
    genre = db.Column(db.String(64), nullable=False, index=True)
    album_art_url = db.Column(db.Text, nullable=True)

    # Audio-feature vector components
    tempo = db.Column(db.Float, nullable=False, default=120.0)   # raw BPM
    energy = db.Column(db.Float, nullable=False, default=0.5)
    danceability = db.Column(db.Float, nullable=False, default=0.5)
    valence = db.Column(db.Float, nullable=False, default=0.5)
    acousticness = db.Column(db.Float, nullable=False, default=0.5)
    instrumentalness = db.Column(db.Float, nullable=False, default=0.0)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "spotify_id": self.spotify_id,
            "name": self.name,
            "artist": self.artist,
            "genre": self.genre,
            "album_art_url": self.album_art_url,
            "tempo": self.tempo,
            "energy": self.energy,
            "danceability": self.danceability,
            "valence": self.valence,
            "acousticness": self.acousticness,
            "instrumentalness": self.instrumentalness,
        }

    def feature_vector(self) -> list[float]:
        """Return a normalised 6-D feature vector for cosine-similarity."""
        return [
            self.tempo / 250.0,          # normalise BPM ÷ 250
            self.energy,
            self.danceability,
            self.valence,
            self.acousticness,
            self.instrumentalness,
        ]

    def __repr__(self) -> str:
        return f"<Track {self.spotify_id!r} — {self.artist} · {self.name}>"


class User(db.Model):
    """
    Spotify-authenticated user (replaces MongoDB 'users' collection).
    top_tracks / top_artists are stored as JSON blobs (Spotify API payloads).
    """

    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    spotify_id = db.Column(db.String(64), unique=True, nullable=False, index=True)
    display_name = db.Column(db.String(256), nullable=True)
    avatar_url = db.Column(db.Text, nullable=True)
    access_token = db.Column(db.Text, nullable=True)      # rotates on every login
    top_tracks = db.Column(db.JSON, nullable=True)        # raw /me/top/tracks payload
    top_artists = db.Column(db.JSON, nullable=True)       # raw /me/top/artists payload
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "spotify_id": self.spotify_id,
            "display_name": self.display_name,
            "avatar_url": self.avatar_url,
            "top_tracks": self.top_tracks,
            "top_artists": self.top_artists,
        }


class Message(db.Model):
    """Optional persistent chat history (one row per message)."""

    __tablename__ = "messages"

    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.String(256), nullable=False, index=True)
    sender_spotify_id = db.Column(db.String(64), nullable=False)
    sender_name = db.Column(db.String(256), nullable=False)
    body = db.Column(db.Text, nullable=False)
    sent_at = db.Column(db.DateTime, default=datetime.utcnow)
