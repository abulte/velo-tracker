import datetime
from typing import Optional
from sqlmodel import Field, SQLModel


class Activity(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)

    # intervals.icu identifiers
    icu_id: str = Field(unique=True, index=True)  # e.g. "A12345678"
    athlete_id: str = Field(index=True)

    # Core fields
    name: str
    sport: str = Field(index=True)  # e.g. "Ride", "VirtualRide", "Run"
    start_date: datetime.datetime = Field(index=True)

    # Distance & time
    distance: Optional[float] = None  # metres
    moving_time: Optional[int] = None  # seconds
    elapsed_time: Optional[int] = None  # seconds
    total_elevation_gain: Optional[float] = None  # metres

    # Power
    average_watts: Optional[float] = None
    normalized_watts: Optional[float] = None
    max_watts: Optional[int] = None
    weighted_average_watts: Optional[float] = None

    # Heart rate
    average_heartrate: Optional[float] = None
    max_heartrate: Optional[int] = None

    # Cycling metrics
    average_cadence: Optional[float] = None
    average_speed: Optional[float] = None  # m/s
    max_speed: Optional[float] = None  # m/s

    # Training load
    tss: Optional[float] = None
    intensity_factor: Optional[float] = None
    icu_training_load: Optional[float] = None

    # Subjective feedback (from Garmin device input, synced via intervals.icu)
    icu_rpe: Optional[int] = None    # RPE 1–10 (entered on device post-ride)
    feel: Optional[int] = None       # Feel 1–5 (1=terrible, 5=great)

    # Local notes (stored only in this app)
    notes: Optional[str] = None

    # Metadata
    description: Optional[str] = None
    synced_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)
    updated_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)
