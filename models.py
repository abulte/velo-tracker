import datetime
from typing import Optional
from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel


class Route(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    reference_activity_id: str  # garmin_id of the reference activity
    created_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)
    garmin_course_url: Optional[str] = None


class Activity(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)

    # Garmin Connect identifier
    garmin_id: str = Field(unique=True, index=True)  # activityId as string

    # Core fields
    name: str
    activity_type: str = Field(index=True)  # typeKey: road_biking, gravel_cycling, etc.
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
    training_load: Optional[float] = None

    # Subjective feedback (from Garmin device post-ride)
    rpe: Optional[int] = None    # directWorkoutRpe (0-100 scale from Garmin)
    feel: Optional[int] = None   # directWorkoutFeel (0-100 scale from Garmin)

    # Map data
    polyline: Optional[list] = Field(default=None, sa_column=Column(JSON))  # [[lat, lon], ...]

    # Route assignment
    route_id: Optional[int] = Field(default=None, foreign_key="route.id", index=True)

    # Local notes (stored only in this app)
    notes: Optional[str] = None

    # Metadata
    description: Optional[str] = None
    synced_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)
    updated_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)
