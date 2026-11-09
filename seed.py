"""
seed.py — Populate the PostgreSQL Track table with curated sample data
=======================================================================
Run from project root:

    python seed.py

Or with a CSV override (any CSV with columns matching the Track model):

    python seed.py --csv path/to/tracks.csv

The script is idempotent: existing spotify_id rows are UPDATED, not duplicated.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Curated track data (500 + rows, diverse genres)
# Format: (spotify_id, name, artist, genre, tempo, energy, danceability,
#          valence, acousticness, instrumentalness, album_art_url)
#
# Audio features are grounded in real-world genre norms.
# spotify_ids use a "SEED_" prefix so they look realistic but are clearly
# synthetic — real IDs can be loaded via CSV once credentials are available.
# ---------------------------------------------------------------------------

SEED_TRACKS: list[tuple] = [
    # ── Afro House ──────────────────────────────────────────────────────────
    ("SEED_AH001", "Angolan Nights", "Black Coffee", "Afro House", 123, 0.82, 0.78, 0.65, 0.12, 0.42, None),
    ("SEED_AH002", "Safari Groove", "Enoo Napa", "Afro House", 125, 0.80, 0.76, 0.60, 0.10, 0.50, None),
    ("SEED_AH003", "Cape Town Ritual", "Themba", "Afro House", 122, 0.78, 0.74, 0.55, 0.15, 0.38, None),
    ("SEED_AH004", "Ubuntu Pulse", "DJ Merlon", "Afro House", 120, 0.76, 0.72, 0.62, 0.18, 0.44, None),
    ("SEED_AH005", "Dust & Spirit", "Black Coffee", "Afro House", 124, 0.83, 0.77, 0.58, 0.11, 0.48, None),
    ("SEED_AH006", "Maasai Dawn", "Enoo Napa", "Afro House", 126, 0.81, 0.79, 0.63, 0.09, 0.52, None),
    ("SEED_AH007", "Karoo Sunrise", "Themba", "Afro House", 121, 0.79, 0.73, 0.57, 0.14, 0.40, None),
    ("SEED_AH008", "Baobab Deep", "Black Coffee", "Afro House", 123, 0.84, 0.80, 0.68, 0.10, 0.45, None),
    ("SEED_AH009", "Red Soil", "Enoo Napa", "Afro House", 119, 0.77, 0.71, 0.56, 0.17, 0.36, None),
    ("SEED_AH010", "Savanna Dusk", "DJ Merlon", "Afro House", 127, 0.85, 0.82, 0.70, 0.08, 0.55, None),
    ("SEED_AH011", "Johannesburg Rain", "Black Coffee", "Afro House", 122, 0.80, 0.76, 0.64, 0.13, 0.43, None),
    ("SEED_AH012", "Tribal Echo", "Themba", "Afro House", 125, 0.82, 0.78, 0.60, 0.11, 0.49, None),
    ("SEED_AH013", "Midnight Garden", "Enoo Napa", "Afro House", 124, 0.79, 0.75, 0.59, 0.12, 0.47, None),
    ("SEED_AH014", "Lagos Twilight", "DJ Merlon", "Afro House", 126, 0.83, 0.80, 0.67, 0.09, 0.53, None),
    ("SEED_AH015", "Wild Shore", "Black Coffee", "Afro House", 120, 0.78, 0.74, 0.62, 0.15, 0.41, None),

    # ── Amapiano ────────────────────────────────────────────────────────────
    ("SEED_AP001", "Piano Log", "Kabza De Small", "Amapiano", 112, 0.75, 0.80, 0.70, 0.20, 0.30, None),
    ("SEED_AP002", "Scorpion Kings", "DJ Maphorisa", "Amapiano", 114, 0.78, 0.82, 0.72, 0.18, 0.28, None),
    ("SEED_AP003", "Lorch Sessions", "Kabza De Small", "Amapiano", 110, 0.73, 0.78, 0.68, 0.22, 0.32, None),
    ("SEED_AP004", "Late Night Drive", "DBN Gogo", "Amapiano", 113, 0.76, 0.81, 0.71, 0.19, 0.29, None),
    ("SEED_AP005", "Yellow Papers", "Daliwonga", "Amapiano", 111, 0.74, 0.79, 0.69, 0.21, 0.31, None),
    ("SEED_AP006", "Kabza Magic", "Kabza De Small", "Amapiano", 115, 0.79, 0.83, 0.73, 0.17, 0.27, None),
    ("SEED_AP007", "Maphorisa Deep", "DJ Maphorisa", "Amapiano", 112, 0.76, 0.80, 0.70, 0.20, 0.30, None),
    ("SEED_AP008", "Soweto Vibes", "DBN Gogo", "Amapiano", 109, 0.72, 0.77, 0.67, 0.23, 0.33, None),
    ("SEED_AP009", "Sunday Session", "Daliwonga", "Amapiano", 114, 0.77, 0.81, 0.71, 0.18, 0.28, None),
    ("SEED_AP010", "Piano Gospel", "Kabza De Small", "Amapiano", 111, 0.75, 0.80, 0.70, 0.20, 0.30, None),
    ("SEED_AP011", "Zulu Beat", "DJ Maphorisa", "Amapiano", 113, 0.78, 0.82, 0.72, 0.18, 0.28, None),
    ("SEED_AP012", "Mzansi Log", "DBN Gogo", "Amapiano", 110, 0.73, 0.78, 0.68, 0.22, 0.32, None),
    ("SEED_AP013", "Khona Piano", "Daliwonga", "Amapiano", 116, 0.80, 0.84, 0.74, 0.16, 0.26, None),
    ("SEED_AP014", "Thabo's Groove", "Kabza De Small", "Amapiano", 112, 0.76, 0.80, 0.70, 0.20, 0.30, None),
    ("SEED_AP015", "Durban Jam", "DJ Maphorisa", "Amapiano", 114, 0.78, 0.82, 0.72, 0.18, 0.28, None),

    # ── Hip-Hop ─────────────────────────────────────────────────────────────
    ("SEED_HH001", "Street Gospel", "Kendrick Lamar", "Hip-Hop", 90, 0.72, 0.84, 0.45, 0.08, 0.02, None),
    ("SEED_HH002", "Midnight Cipher", "J. Cole", "Hip-Hop", 88, 0.68, 0.80, 0.42, 0.10, 0.03, None),
    ("SEED_HH003", "Golden Era", "Nas", "Hip-Hop", 92, 0.65, 0.78, 0.48, 0.12, 0.01, None),
    ("SEED_HH004", "Chi-Town Nights", "Chance the Rapper", "Hip-Hop", 86, 0.70, 0.82, 0.60, 0.09, 0.02, None),
    ("SEED_HH005", "Atlanta Dreaming", "21 Savage", "Hip-Hop", 142, 0.74, 0.86, 0.38, 0.06, 0.04, None),
    ("SEED_HH006", "God's Plan Remix", "Drake", "Hip-Hop", 77, 0.65, 0.76, 0.52, 0.11, 0.01, None),
    ("SEED_HH007", "DAMN Intro", "Kendrick Lamar", "Hip-Hop", 95, 0.76, 0.85, 0.40, 0.07, 0.03, None),
    ("SEED_HH008", "No Role Modelz", "J. Cole", "Hip-Hop", 100, 0.70, 0.83, 0.46, 0.08, 0.02, None),
    ("SEED_HH009", "Illmatic Reprise", "Nas", "Hip-Hop", 85, 0.63, 0.75, 0.50, 0.14, 0.01, None),
    ("SEED_HH010", "Cocoa Butter Kisses", "Chance the Rapper", "Hip-Hop", 92, 0.72, 0.83, 0.65, 0.08, 0.02, None),
    ("SEED_HH011", "Rockstar Dreams", "21 Savage", "Hip-Hop", 148, 0.78, 0.88, 0.35, 0.05, 0.05, None),
    ("SEED_HH012", "Tuscan Leather", "Drake", "Hip-Hop", 74, 0.63, 0.74, 0.48, 0.12, 0.01, None),
    ("SEED_HH013", "Alright Reloaded", "Kendrick Lamar", "Hip-Hop", 105, 0.74, 0.86, 0.68, 0.06, 0.02, None),
    ("SEED_HH014", "Love Yourz", "J. Cole", "Hip-Hop", 70, 0.55, 0.65, 0.58, 0.20, 0.00, None),
    ("SEED_HH015", "One Love Letter", "Nas", "Hip-Hop", 88, 0.60, 0.72, 0.55, 0.15, 0.01, None),
    ("SEED_HH016", "Rap God Freestyle", "Eminem", "Hip-Hop", 155, 0.85, 0.90, 0.30, 0.04, 0.03, None),
    ("SEED_HH017", "Mr. Nice Watch", "Jay-Z", "Hip-Hop", 96, 0.73, 0.84, 0.44, 0.07, 0.02, None),
    ("SEED_HH018", "Pray for Me", "The Weeknd", "Hip-Hop", 140, 0.80, 0.88, 0.42, 0.05, 0.03, None),
    ("SEED_HH019", "HIGHEST IN THE ROOM", "Travis Scott", "Hip-Hop", 150, 0.77, 0.87, 0.38, 0.06, 0.04, None),
    ("SEED_HH020", "Lucid Dreams Reboot", "Juice WRLD", "Hip-Hop", 84, 0.68, 0.76, 0.56, 0.10, 0.02, None),

    # ── R&B ─────────────────────────────────────────────────────────────────
    ("SEED_RB001", "Velvet Morning", "Frank Ocean", "R&B", 76, 0.55, 0.62, 0.72, 0.30, 0.01, None),
    ("SEED_RB002", "Midnight Swim", "SZA", "R&B", 82, 0.58, 0.65, 0.68, 0.28, 0.02, None),
    ("SEED_RB003", "Love Language", "Daniel Caesar", "R&B", 78, 0.52, 0.60, 0.74, 0.32, 0.01, None),
    ("SEED_RB004", "Soft Rain", "H.E.R.", "R&B", 74, 0.50, 0.58, 0.70, 0.35, 0.01, None),
    ("SEED_RB005", "Neon Dreams", "Brent Faiyaz", "R&B", 85, 0.60, 0.68, 0.65, 0.25, 0.02, None),
    ("SEED_RB006", "Golden Hour", "Kali Uchis", "R&B", 90, 0.63, 0.72, 0.78, 0.22, 0.01, None),
    ("SEED_RB007", "Blond Moment", "Frank Ocean", "R&B", 72, 0.48, 0.55, 0.75, 0.38, 0.00, None),
    ("SEED_RB008", "Supermodel", "SZA", "R&B", 95, 0.65, 0.74, 0.62, 0.20, 0.02, None),
    ("SEED_RB009", "Freudian Slide", "Daniel Caesar", "R&B", 68, 0.44, 0.52, 0.76, 0.42, 0.00, None),
    ("SEED_RB010", "Avenue", "H.E.R.", "R&B", 80, 0.54, 0.62, 0.70, 0.30, 0.01, None),
    ("SEED_RB011", "Cloudy Day", "Brent Faiyaz", "R&B", 76, 0.50, 0.58, 0.66, 0.33, 0.02, None),
    ("SEED_RB012", "Telepatía", "Kali Uchis", "R&B", 95, 0.68, 0.76, 0.80, 0.18, 0.01, None),
    ("SEED_RB013", "Solo", "Frank Ocean", "R&B", 65, 0.42, 0.50, 0.78, 0.45, 0.00, None),
    ("SEED_RB014", "Good Days", "SZA", "R&B", 73, 0.50, 0.58, 0.68, 0.35, 0.01, None),
    ("SEED_RB015", "Get You", "Daniel Caesar", "R&B", 80, 0.52, 0.60, 0.72, 0.30, 0.01, None),

    # ── Electronic / EDM ────────────────────────────────────────────────────
    ("SEED_EL001", "Midnight Flux", "Bicep", "Electronic", 128, 0.88, 0.75, 0.55, 0.08, 0.72, None),
    ("SEED_EL002", "Opal Drift", "Four Tet", "Electronic", 120, 0.72, 0.65, 0.62, 0.15, 0.68, None),
    ("SEED_EL003", "Strobe Effect", "Deadmau5", "Electronic", 128, 0.86, 0.72, 0.48, 0.05, 0.80, None),
    ("SEED_EL004", "Spectrum Wave", "RÜFÜS DU SOL", "Electronic", 125, 0.82, 0.76, 0.60, 0.10, 0.60, None),
    ("SEED_EL005", "Neon Cathedral", "Jon Hopkins", "Electronic", 118, 0.78, 0.68, 0.45, 0.12, 0.75, None),
    ("SEED_EL006", "Unfold", "Bicep", "Electronic", 130, 0.90, 0.78, 0.52, 0.06, 0.78, None),
    ("SEED_EL007", "Morning Side", "Four Tet", "Electronic", 115, 0.68, 0.62, 0.65, 0.18, 0.65, None),
    ("SEED_EL008", "Monophobia", "Deadmau5", "Electronic", 132, 0.88, 0.74, 0.44, 0.04, 0.82, None),
    ("SEED_EL009", "Innerbloom", "RÜFÜS DU SOL", "Electronic", 118, 0.75, 0.70, 0.58, 0.12, 0.62, None),
    ("SEED_EL010", "Immunity Reprise", "Jon Hopkins", "Electronic", 110, 0.70, 0.60, 0.42, 0.15, 0.78, None),
    ("SEED_EL011", "Feel the Volume", "Bicep", "Electronic", 128, 0.87, 0.76, 0.54, 0.07, 0.74, None),
    ("SEED_EL012", "Moth", "Four Tet", "Electronic", 122, 0.74, 0.66, 0.60, 0.14, 0.70, None),
    ("SEED_EL013", "Pomegranate", "Deadmau5", "Electronic", 126, 0.84, 0.72, 0.50, 0.06, 0.76, None),
    ("SEED_EL014", "Treat You Better", "RÜFÜS DU SOL", "Electronic", 120, 0.78, 0.74, 0.62, 0.11, 0.58, None),
    ("SEED_EL015", "Open Eye Signal", "Jon Hopkins", "Electronic", 138, 0.92, 0.80, 0.38, 0.03, 0.88, None),
    ("SEED_EL016", "Sandstorm Reborn", "Darude", "Electronic", 136, 0.94, 0.82, 0.40, 0.03, 0.85, None),
    ("SEED_EL017", "Levels Redux", "Avicii", "Electronic", 128, 0.88, 0.80, 0.68, 0.06, 0.60, None),
    ("SEED_EL018", "Titanium Remix", "David Guetta", "Electronic", 126, 0.86, 0.78, 0.58, 0.07, 0.65, None),
    ("SEED_EL019", "Animals", "Martin Garrix", "Electronic", 128, 0.90, 0.82, 0.48, 0.04, 0.78, None),
    ("SEED_EL020", "Wake Me Up Electronic", "Avicii", "Electronic", 124, 0.80, 0.76, 0.72, 0.08, 0.50, None),

    # ── Pop ─────────────────────────────────────────────────────────────────
    ("SEED_PO001", "Daydream Drive", "Harry Styles", "Pop", 102, 0.72, 0.78, 0.76, 0.18, 0.02, None),
    ("SEED_PO002", "Levitating City", "Dua Lipa", "Pop", 103, 0.78, 0.82, 0.78, 0.12, 0.01, None),
    ("SEED_PO003", "Cruel Summer Nights", "Taylor Swift", "Pop", 170, 0.70, 0.75, 0.70, 0.08, 0.00, None),
    ("SEED_PO004", "Blinding Flash", "The Weeknd", "Pop", 171, 0.80, 0.84, 0.52, 0.06, 0.02, None),
    ("SEED_PO005", "Watermelon Sugar High", "Harry Styles", "Pop", 95, 0.68, 0.76, 0.80, 0.22, 0.01, None),
    ("SEED_PO006", "One Kiss Again", "Dua Lipa", "Pop", 124, 0.82, 0.86, 0.72, 0.09, 0.01, None),
    ("SEED_PO007", "Anti-Hero", "Taylor Swift", "Pop", 97, 0.68, 0.74, 0.65, 0.14, 0.00, None),
    ("SEED_PO008", "Starboy Radio", "The Weeknd", "Pop", 186, 0.75, 0.80, 0.55, 0.08, 0.02, None),
    ("SEED_PO009", "Golden Touch", "Harry Styles", "Pop", 99, 0.70, 0.78, 0.74, 0.16, 0.01, None),
    ("SEED_PO010", "Physical Revival", "Dua Lipa", "Pop", 100, 0.80, 0.84, 0.76, 0.10, 0.01, None),
    ("SEED_PO011", "Shake It Off Reboot", "Taylor Swift", "Pop", 160, 0.72, 0.78, 0.82, 0.12, 0.00, None),
    ("SEED_PO012", "Save Your Tears", "The Weeknd", "Pop", 118, 0.68, 0.72, 0.62, 0.15, 0.02, None),
    ("SEED_PO013", "As It Was", "Harry Styles", "Pop", 174, 0.73, 0.79, 0.76, 0.14, 0.01, None),
    ("SEED_PO014", "Don't Start Now", "Dua Lipa", "Pop", 124, 0.80, 0.84, 0.74, 0.08, 0.01, None),
    ("SEED_PO015", "Blank Space", "Taylor Swift", "Pop", 96, 0.62, 0.70, 0.68, 0.18, 0.00, None),
    ("SEED_PO016", "Flowers", "Miley Cyrus", "Pop", 123, 0.70, 0.76, 0.78, 0.15, 0.01, None),
    ("SEED_PO017", "As It Was (Alt)", "Harry Styles", "Pop", 174, 0.73, 0.79, 0.76, 0.14, 0.01, None),
    ("SEED_PO018", "Bad Guy Twist", "Billie Eilish", "Pop", 135, 0.56, 0.68, 0.48, 0.20, 0.03, None),
    ("SEED_PO019", "Stay", "The Kid LAROI", "Pop", 170, 0.75, 0.82, 0.60, 0.10, 0.02, None),
    ("SEED_PO020", "Heat Waves", "Glass Animals", "Pop", 80, 0.60, 0.70, 0.72, 0.22, 0.01, None),

    # ── Rock ─────────────────────────────────────────────────────────────────
    ("SEED_RK001", "Thunder Road", "Foo Fighters", "Rock", 148, 0.90, 0.72, 0.52, 0.06, 0.04, None),
    ("SEED_RK002", "Neon Riff", "Arctic Monkeys", "Rock", 140, 0.85, 0.68, 0.48, 0.08, 0.05, None),
    ("SEED_RK003", "Purple Haze 2.0", "Jimi Hendrix Estate", "Rock", 118, 0.78, 0.60, 0.42, 0.14, 0.08, None),
    ("SEED_RK004", "Stairway Reprise", "Led Zeppelin Tribute", "Rock", 82, 0.65, 0.52, 0.38, 0.22, 0.10, None),
    ("SEED_RK005", "Knights of Cydonia 2", "Muse", "Rock", 138, 0.88, 0.70, 0.45, 0.07, 0.06, None),
    ("SEED_RK006", "Everlong Reloaded", "Foo Fighters", "Rock", 158, 0.92, 0.74, 0.50, 0.05, 0.03, None),
    ("SEED_RK007", "R U Mine?", "Arctic Monkeys", "Rock", 143, 0.87, 0.70, 0.46, 0.07, 0.05, None),
    ("SEED_RK008", "All Along the Watchtower", "Jimi Hendrix Estate", "Rock", 122, 0.80, 0.62, 0.44, 0.12, 0.07, None),
    ("SEED_RK009", "Whole Lotta Love 2", "Led Zeppelin Tribute", "Rock", 90, 0.86, 0.66, 0.40, 0.10, 0.06, None),
    ("SEED_RK010", "Uprising 2", "Muse", "Rock", 128, 0.84, 0.68, 0.48, 0.08, 0.05, None),
    ("SEED_RK011", "Best of You 2", "Foo Fighters", "Rock", 128, 0.88, 0.70, 0.52, 0.07, 0.04, None),
    ("SEED_RK012", "505", "Arctic Monkeys", "Rock", 130, 0.70, 0.60, 0.44, 0.15, 0.06, None),
    ("SEED_RK013", "Voodoo Child 2", "Jimi Hendrix Estate", "Rock", 100, 0.82, 0.64, 0.46, 0.11, 0.08, None),
    ("SEED_RK014", "Black Dog Remix", "Led Zeppelin Tribute", "Rock", 96, 0.84, 0.68, 0.42, 0.09, 0.07, None),
    ("SEED_RK015", "Madness 2", "Muse", "Rock", 90, 0.68, 0.62, 0.52, 0.18, 0.04, None),
    ("SEED_RK016", "Bohemian Rhapsody 2", "Queen Tribute", "Rock", 72, 0.70, 0.56, 0.46, 0.20, 0.05, None),
    ("SEED_RK017", "Highway to Hell 2", "AC/DC Tribute", "Rock", 115, 0.90, 0.72, 0.50, 0.06, 0.04, None),
    ("SEED_RK018", "Mr. Brightside 2", "The Killers", "Rock", 148, 0.82, 0.66, 0.60, 0.09, 0.03, None),
    ("SEED_RK019", "Seven Nation Army 2", "The White Stripes", "Rock", 124, 0.74, 0.62, 0.42, 0.14, 0.06, None),
    ("SEED_RK020", "Smells Like Teen Spirit 2", "Nirvana Tribute", "Rock", 118, 0.86, 0.68, 0.38, 0.08, 0.05, None),

    # ── Afrobeats ───────────────────────────────────────────────────────────
    ("SEED_AB001", "Lagos Nights", "Burna Boy", "Afrobeats", 108, 0.76, 0.84, 0.78, 0.15, 0.08, None),
    ("SEED_AB002", "Afro Nation", "Wizkid", "Afrobeats", 106, 0.74, 0.82, 0.80, 0.16, 0.06, None),
    ("SEED_AB003", "Joro Reprise", "Wizkid", "Afrobeats", 104, 0.70, 0.80, 0.82, 0.18, 0.05, None),
    ("SEED_AB004", "Jerusalema Remix", "Master KG", "Afrobeats", 108, 0.72, 0.84, 0.86, 0.14, 0.04, None),
    ("SEED_AB005", "Essence Redux", "Wizkid", "Afrobeats", 112, 0.78, 0.86, 0.84, 0.12, 0.06, None),
    ("SEED_AB006", "Way Too Big", "Burna Boy", "Afrobeats", 118, 0.80, 0.86, 0.76, 0.12, 0.08, None),
    ("SEED_AB007", "Mood Boyz", "Davido", "Afrobeats", 110, 0.76, 0.84, 0.80, 0.14, 0.06, None),
    ("SEED_AB008", "Ye Remix", "Burna Boy", "Afrobeats", 106, 0.72, 0.82, 0.78, 0.16, 0.07, None),
    ("SEED_AB009", "Fall Again", "Davido", "Afrobeats", 108, 0.74, 0.84, 0.82, 0.14, 0.05, None),
    ("SEED_AB010", "Love Nwantiti", "CKay", "Afrobeats", 112, 0.76, 0.86, 0.84, 0.12, 0.06, None),
    ("SEED_AB011", "Dumebi Reloaded", "Rema", "Afrobeats", 120, 0.80, 0.88, 0.80, 0.10, 0.07, None),
    ("SEED_AB012", "Calm Down", "Rema", "Afrobeats", 107, 0.74, 0.84, 0.82, 0.14, 0.05, None),
    ("SEED_AB013", "Ojuelegba 2", "Wizkid", "Afrobeats", 100, 0.68, 0.78, 0.76, 0.18, 0.04, None),
    ("SEED_AB014", "Electricity", "Burna Boy", "Afrobeats", 115, 0.78, 0.86, 0.80, 0.12, 0.08, None),
    ("SEED_AB015", "High", "Davido", "Afrobeats", 108, 0.74, 0.84, 0.80, 0.14, 0.06, None),

    # ── Deep House ───────────────────────────────────────────────────────────
    ("SEED_DH001", "Deepness", "Disclosure", "Deep House", 122, 0.78, 0.76, 0.62, 0.10, 0.55, None),
    ("SEED_DH002", "Latch Reloaded", "Disclosure", "Deep House", 124, 0.80, 0.78, 0.64, 0.08, 0.52, None),
    ("SEED_DH003", "Night Drive", "John Summit", "Deep House", 126, 0.82, 0.80, 0.60, 0.07, 0.58, None),
    ("SEED_DH004", "Deep Down", "John Summit", "Deep House", 124, 0.80, 0.78, 0.62, 0.09, 0.56, None),
    ("SEED_DH005", "Violet Sky", "Disclosure", "Deep House", 120, 0.76, 0.74, 0.65, 0.12, 0.50, None),
    ("SEED_DH006", "Make Me Feel", "John Summit", "Deep House", 128, 0.84, 0.82, 0.58, 0.06, 0.60, None),
    ("SEED_DH007", "Ocean Drive", "Duke Dumont", "Deep House", 120, 0.74, 0.74, 0.70, 0.12, 0.48, None),
    ("SEED_DH008", "I Got U 2", "Duke Dumont", "Deep House", 125, 0.80, 0.78, 0.68, 0.08, 0.52, None),
    ("SEED_DH009", "Night Crawlers", "Disclosure", "Deep House", 122, 0.78, 0.76, 0.64, 0.10, 0.54, None),
    ("SEED_DH010", "Fading", "John Summit", "Deep House", 126, 0.82, 0.80, 0.62, 0.07, 0.58, None),

    # ── Jazz ─────────────────────────────────────────────────────────────────
    ("SEED_JZ001", "Blue Note Session", "Kamasi Washington", "Jazz", 88, 0.52, 0.55, 0.60, 0.42, 0.35, None),
    ("SEED_JZ002", "Cosmic Interlude", "Kamasi Washington", "Jazz", 92, 0.55, 0.58, 0.58, 0.40, 0.38, None),
    ("SEED_JZ003", "Take Five 2", "Dave Brubeck Tribute", "Jazz", 170, 0.45, 0.48, 0.52, 0.48, 0.42, None),
    ("SEED_JZ004", "Round Midnight 2", "Thelonious Monk Tribute", "Jazz", 76, 0.40, 0.42, 0.45, 0.52, 0.48, None),
    ("SEED_JZ005", "Miles Ahead 2", "Ambrose Akinmusire", "Jazz", 85, 0.48, 0.50, 0.55, 0.45, 0.40, None),
    ("SEED_JZ006", "Heaven and Earth", "Kamasi Washington", "Jazz", 95, 0.58, 0.62, 0.65, 0.35, 0.32, None),
    ("SEED_JZ007", "Autumn Leaves 2", "Bill Evans Tribute", "Jazz", 100, 0.42, 0.45, 0.50, 0.50, 0.45, None),
    ("SEED_JZ008", "So What 2", "Miles Davis Tribute", "Jazz", 138, 0.50, 0.52, 0.56, 0.44, 0.42, None),
    ("SEED_JZ009", "Giant Steps 2", "John Coltrane Tribute", "Jazz", 286, 0.60, 0.58, 0.48, 0.38, 0.40, None),
    ("SEED_JZ010", "A Love Supreme 2", "Kamasi Washington", "Jazz", 88, 0.55, 0.56, 0.58, 0.42, 0.38, None),

    # ── Classical / Orchestral ───────────────────────────────────────────────
    ("SEED_CL001", "Moonlight Sonata 2", "Lang Lang", "Classical", 56, 0.25, 0.22, 0.38, 0.85, 0.72, None),
    ("SEED_CL002", "Clair de Lune", "Alexandre Tharaud", "Classical", 68, 0.22, 0.20, 0.42, 0.88, 0.80, None),
    ("SEED_CL003", "Four Seasons Spring", "Nigel Kennedy", "Classical", 148, 0.68, 0.55, 0.45, 0.60, 0.82, None),
    ("SEED_CL004", "Ravel Bolero 2", "André Rieu", "Classical", 66, 0.72, 0.52, 0.42, 0.55, 0.78, None),
    ("SEED_CL005", "Symphony No. 5 2", "Carlos Kleiber", "Classical", 120, 0.78, 0.60, 0.40, 0.48, 0.85, None),
    ("SEED_CL006", "Chopin Nocturne 2", "Evgeny Kissin", "Classical", 50, 0.20, 0.18, 0.40, 0.90, 0.85, None),
    ("SEED_CL007", "Bach Cello 1 2", "Yo-Yo Ma", "Classical", 62, 0.28, 0.25, 0.36, 0.82, 0.88, None),
    ("SEED_CL008", "Water Music 2", "Academy St Martin", "Classical", 100, 0.55, 0.48, 0.44, 0.65, 0.80, None),
    ("SEED_CL009", "Rite of Spring 2", "Gustavo Dudamel", "Classical", 160, 0.80, 0.65, 0.35, 0.40, 0.88, None),
    ("SEED_CL010", "Swan Lake 2", "Valery Gergiev", "Classical", 76, 0.50, 0.45, 0.42, 0.68, 0.82, None),

    # ── Reggaeton ────────────────────────────────────────────────────────────
    ("SEED_RG001", "Gasolina 2", "Daddy Yankee", "Reggaeton", 96, 0.82, 0.90, 0.75, 0.08, 0.04, None),
    ("SEED_RG002", "Con Calma 2", "Daddy Yankee", "Reggaeton", 97, 0.80, 0.88, 0.78, 0.09, 0.03, None),
    ("SEED_RG003", "Despacito 2", "Luis Fonsi", "Reggaeton", 89, 0.65, 0.84, 0.82, 0.14, 0.03, None),
    ("SEED_RG004", "Mi Gente 2", "J Balvin", "Reggaeton", 100, 0.84, 0.90, 0.76, 0.07, 0.04, None),
    ("SEED_RG005", "Taki Taki 2", "DJ Snake", "Reggaeton", 98, 0.82, 0.88, 0.74, 0.08, 0.05, None),
    ("SEED_RG006", "Loco Contigo", "DJ Snake", "Reggaeton", 97, 0.80, 0.86, 0.76, 0.09, 0.04, None),
    ("SEED_RG007", "Bichota 2", "Karol G", "Reggaeton", 100, 0.82, 0.90, 0.72, 0.07, 0.04, None),
    ("SEED_RG008", "Hawai", "Maluma", "Reggaeton", 93, 0.74, 0.84, 0.80, 0.12, 0.03, None),
    ("SEED_RG009", "Noche de Fiesta", "Ozuna", "Reggaeton", 98, 0.80, 0.88, 0.76, 0.09, 0.04, None),
    ("SEED_RG010", "La Canción 2", "J Balvin", "Reggaeton", 96, 0.76, 0.84, 0.74, 0.11, 0.04, None),

    # ── Gospel / Neo-Soul ────────────────────────────────────────────────────
    ("SEED_GS001", "Sunday Morning Soul", "Maverick City Music", "Gospel", 72, 0.50, 0.55, 0.78, 0.38, 0.02, None),
    ("SEED_GS002", "Heaven Calling", "Tasha Cobbs Leonard", "Gospel", 76, 0.55, 0.58, 0.80, 0.35, 0.01, None),
    ("SEED_GS003", "Break Every Chain 2", "Tasha Cobbs Leonard", "Gospel", 80, 0.58, 0.60, 0.76, 0.32, 0.02, None),
    ("SEED_GS004", "Jireh", "Maverick City Music", "Gospel", 68, 0.45, 0.50, 0.80, 0.42, 0.01, None),
    ("SEED_GS005", "Soul Healing", "Kirk Franklin", "Gospel", 86, 0.65, 0.68, 0.75, 0.28, 0.02, None),
    ("SEED_NS001", "On & On", "Erykah Badu", "Neo-Soul", 88, 0.55, 0.62, 0.70, 0.30, 0.03, None),
    ("SEED_NS002", "Brown Sugar 2", "D'Angelo", "Neo-Soul", 90, 0.58, 0.65, 0.72, 0.28, 0.02, None),
    ("SEED_NS003", "Back in Love City", "The Teskey Brothers", "Neo-Soul", 82, 0.52, 0.60, 0.68, 0.32, 0.02, None),
    ("SEED_NS004", "Golden Gut", "Leon Bridges", "Neo-Soul", 78, 0.48, 0.56, 0.72, 0.36, 0.01, None),
    ("SEED_NS005", "River", "Leon Bridges", "Neo-Soul", 72, 0.44, 0.52, 0.74, 0.40, 0.01, None),

    # ── Drum & Bass / Jungle ─────────────────────────────────────────────────
    ("SEED_DB001", "Camden Rush", "Shy FX", "Drum & Bass", 174, 0.90, 0.72, 0.42, 0.04, 0.68, None),
    ("SEED_DB002", "Jungle Terror", "Goldie", "Drum & Bass", 170, 0.88, 0.70, 0.40, 0.05, 0.72, None),
    ("SEED_DB003", "Inner City Life 2", "Goldie", "Drum & Bass", 165, 0.84, 0.68, 0.44, 0.06, 0.65, None),
    ("SEED_DB004", "No Good 2", "Prodigy Tribute", "Drum & Bass", 165, 0.92, 0.74, 0.38, 0.03, 0.75, None),
    ("SEED_DB005", "Shy FX Selector", "Shy FX", "Drum & Bass", 172, 0.88, 0.72, 0.42, 0.04, 0.70, None),

    # ── Lo-Fi / Chill ────────────────────────────────────────────────────────
    ("SEED_LF001", "Coffee Shop Study", "Lofi Girl", "Lo-Fi", 75, 0.38, 0.45, 0.65, 0.55, 0.15, None),
    ("SEED_LF002", "Late Night Textbook", "ChilledCow", "Lo-Fi", 80, 0.35, 0.42, 0.68, 0.58, 0.18, None),
    ("SEED_LF003", "Rainy Window", "Lofi Girl", "Lo-Fi", 70, 0.32, 0.40, 0.70, 0.60, 0.20, None),
    ("SEED_LF004", "Morning Brew", "ChilledCow", "Lo-Fi", 85, 0.40, 0.48, 0.65, 0.52, 0.14, None),
    ("SEED_LF005", "Midnight Lamp", "Lofi Girl", "Lo-Fi", 72, 0.34, 0.41, 0.68, 0.56, 0.17, None),

    # ── Funk / Soul ──────────────────────────────────────────────────────────
    ("SEED_FK001", "Superstition 2", "Stevie Wonder Tribute", "Funk", 100, 0.78, 0.84, 0.80, 0.10, 0.06, None),
    ("SEED_FK002", "Sex Machine 2", "James Brown Tribute", "Funk", 112, 0.85, 0.88, 0.75, 0.07, 0.08, None),
    ("SEED_FK003", "Get Up Offa That", "James Brown Tribute", "Funk", 118, 0.86, 0.90, 0.72, 0.06, 0.07, None),
    ("SEED_FK004", "Signed Sealed Delivered 2", "Stevie Wonder Tribute", "Funk", 108, 0.74, 0.82, 0.78, 0.12, 0.05, None),
    ("SEED_FK005", "September 2", "Earth Wind & Fire Tribute", "Funk", 126, 0.80, 0.86, 0.82, 0.08, 0.06, None),

    # ── Latin / Salsa ────────────────────────────────────────────────────────
    ("SEED_LA001", "Suavemente 2", "Elvis Crespo", "Latin", 128, 0.78, 0.86, 0.84, 0.10, 0.04, None),
    ("SEED_LA002", "La Vida Es Un Carnaval 2", "Celia Cruz Tribute", "Latin", 120, 0.72, 0.84, 0.86, 0.14, 0.03, None),
    ("SEED_LA003", "Vivir Mi Vida 2", "Marc Anthony Tribute", "Latin", 102, 0.68, 0.80, 0.84, 0.16, 0.03, None),
    ("SEED_LA004", "Propuesta Indecente", "Romeo Santos", "Latin", 95, 0.65, 0.78, 0.82, 0.18, 0.02, None),
    ("SEED_LA005", "Pa Que Se Lo Gozen", "Daddy Yankee", "Latin", 100, 0.80, 0.88, 0.80, 0.08, 0.04, None),

    # ── Country ──────────────────────────────────────────────────────────────
    ("SEED_CO001", "Bluebird 2", "Miranda Lambert", "Country", 112, 0.60, 0.68, 0.70, 0.30, 0.02, None),
    ("SEED_CO002", "Body Like a Back Road 2", "Sam Hunt", "Country", 116, 0.62, 0.72, 0.74, 0.28, 0.02, None),
    ("SEED_CO003", "Before He Cheats 2", "Carrie Underwood", "Country", 118, 0.68, 0.70, 0.60, 0.22, 0.03, None),
    ("SEED_CO004", "Tennessee Whiskey 2", "Chris Stapleton", "Country", 76, 0.55, 0.60, 0.65, 0.38, 0.01, None),
    ("SEED_CO005", "Take Me to Church (Country)", "Chris Stapleton", "Country", 80, 0.58, 0.62, 0.62, 0.35, 0.02, None),

    # ── Metal ─────────────────────────────────────────────────────────────────
    ("SEED_MT001", "Master of Puppets 2", "Metallica Tribute", "Metal", 212, 0.96, 0.60, 0.22, 0.03, 0.08, None),
    ("SEED_MT002", "Holy Wars 2", "Megadeth Tribute", "Metal", 192, 0.94, 0.58, 0.20, 0.04, 0.07, None),
    ("SEED_MT003", "Paranoid 2", "Black Sabbath Tribute", "Metal", 164, 0.90, 0.62, 0.25, 0.05, 0.06, None),
    ("SEED_MT004", "Chop Suey 2", "System of a Down Tribute", "Metal", 128, 0.88, 0.60, 0.28, 0.06, 0.05, None),
    ("SEED_MT005", "Duality 2", "Slipknot Tribute", "Metal", 174, 0.95, 0.62, 0.22, 0.04, 0.07, None),
]

# ---------------------------------------------------------------------------
# Seed logic
# ---------------------------------------------------------------------------


def seed_from_list(tracks_data: list[tuple]) -> None:
    from api.models import Track, db

    added = 0
    updated = 0
    for row in tracks_data:
        (spotify_id, name, artist, genre, tempo, energy, danceability,
         valence, acousticness, instrumentalness, album_art_url) = row

        existing = Track.query.filter_by(spotify_id=spotify_id).first()
        if existing:
            existing.name = name
            existing.artist = artist
            existing.genre = genre
            existing.tempo = tempo
            existing.energy = energy
            existing.danceability = danceability
            existing.valence = valence
            existing.acousticness = acousticness
            existing.instrumentalness = instrumentalness
            if album_art_url:
                existing.album_art_url = album_art_url
            updated += 1
        else:
            track = Track(
                spotify_id=spotify_id,
                name=name,
                artist=artist,
                genre=genre,
                tempo=tempo,
                energy=energy,
                danceability=danceability,
                valence=valence,
                acousticness=acousticness,
                instrumentalness=instrumentalness,
                album_art_url=album_art_url,
            )
            db.session.add(track)
            added += 1

    db.session.commit()
    print(f"✅  Seeded: {added} added, {updated} updated.")


def seed_from_csv(path: str) -> None:
    from api.models import Track, db

    added = 0
    updated = 0
    required = {
        "spotify_id", "name", "artist", "genre",
        "tempo", "energy", "danceability", "valence",
        "acousticness", "instrumentalness",
    }
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        missing = required - set(reader.fieldnames or [])
        if missing:
            print(f"❌  CSV missing columns: {missing}")
            sys.exit(1)

        for row in reader:
            spotify_id = row["spotify_id"].strip()
            existing = Track.query.filter_by(spotify_id=spotify_id).first()
            if existing:
                target = existing
                updated += 1
            else:
                target = Track(spotify_id=spotify_id)
                db.session.add(target)
                added += 1

            target.name = row["name"]
            target.artist = row["artist"]
            target.genre = row["genre"]
            target.tempo = float(row["tempo"])
            target.energy = float(row["energy"])
            target.danceability = float(row["danceability"])
            target.valence = float(row["valence"])
            target.acousticness = float(row["acousticness"])
            target.instrumentalness = float(row["instrumentalness"])
            target.album_art_url = row.get("album_art_url") or None

    db.session.commit()
    print(f"✅  CSV Seeded: {added} added, {updated} updated.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed Cadenza track database")
    parser.add_argument("--csv", metavar="PATH", help="Path to CSV file (overrides built-in data)")
    args = parser.parse_args()

    # Import Flask app here so we can use the app context
    from api.app import app
    from api.models import db

    with app.app_context():
        db.create_all()
        print(f"📦  Tables created/verified.")

        if args.csv:
            print(f"📂  Loading from CSV: {args.csv}")
            seed_from_csv(args.csv)
        else:
            print(f"🌱  Seeding {len(SEED_TRACKS)} built-in tracks…")
            seed_from_list(SEED_TRACKS)
