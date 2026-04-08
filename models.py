import datetime
from typing import Optional
from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel


class UserProfile(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    ftp: Optional[int] = None  # watts
    weight_kg: Optional[float] = None
    # per-day hours templates: {"mon": 0, "tue": 1.5, "wed": 0, "thu": 1.5, "fri": 0, "sat": 4, "sun": 2.5}
    week_a: Optional[dict[str, float]] = Field(default=None, sa_column=Column(JSON))
    week_b: Optional[dict[str, float]] = Field(default=None, sa_column=Column(JSON))
    # intervals.icu
    icu_athlete_id: Optional[str] = None
    icu_api_key: Optional[str] = None
    peak_ctl: Optional[float] = None
    athlete_level: Optional[str] = None  # "recreational" | "amateur" | "competitive" | "elite"
    icu_synced_at: Optional[datetime.datetime] = None
    updated_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)



class Goal(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    goal_type: str  # "race" | "ftp" | "endurance"
    target_date: datetime.date
    target_ftp: Optional[int] = None  # watts, used when goal_type == "ftp"
    notes: Optional[str] = None
    is_active: bool = False
    created_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)


class TrainingPlan(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    goal_id: int = Field(foreign_key="goal.id", index=True)
    generated_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)
    start_date: Optional[datetime.date] = Field(default=None)  # Monday of week 1
    summary: str
    rationale: Optional[str] = None  # full coaching analysis from turn 1
    is_active: bool = False


class TrainingWeek(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    plan_id: int = Field(foreign_key="trainingplan.id", index=True)
    week_number: int  # 1-indexed
    phase: str  # "base" | "build" | "peak" | "taper"
    tss_target: int
    description: str
    week_start: Optional[datetime.date] = Field(default=None)  # Monday of that week, set at generation
    stale: bool = Field(default=False)  # True when availability changed since generation
    week_type: str = Field(default="a")  # "a" | "b" | "custom"
    avail_override: Optional[dict[str, float]] = Field(default=None, sa_column=Column(JSON))  # per-day hours, only when week_type="custom"


class TrainingSession(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    week_id: int = Field(foreign_key="trainingweek.id", index=True)
    day_of_week: str  # "mon" | "tue" | "wed" | "thu" | "fri" | "sat" | "sun"
    session_type: str  # "endurance" | "threshold" | "vo2max" | "recovery" | "long"
    tss_target: int
    duration_min: int
    title: str
    notes: Optional[str] = None
    # Structured workout steps — generated on demand when session detail is first viewed.
    # Each step: {type, duration_sec, power_low, power_high, repeat?, cadence?, description?}
    steps: Optional[list[dict[str, object]]] = Field(default=None, sa_column=Column(JSON))


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
