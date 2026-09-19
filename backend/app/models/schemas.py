"""数据模型定义"""

from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from typing import List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ============ 请求模型 ============

class ValueEnum(str, Enum):
    def __str__(self) -> str:
        return self.value


class TransportationMode(ValueEnum):
    PUBLIC_TRANSIT = "公共交通"
    DRIVING = "自驾"
    WALKING = "步行"
    MIXED = "混合"


class AccommodationType(ValueEnum):
    ECONOMY_HOTEL = "经济型酒店"
    COMFORT_HOTEL = "舒适型酒店"
    LUXURY_HOTEL = "豪华酒店"
    HOMESTAY = "民宿"


class TripRequest(BaseModel):
    """Backward-compatible request with optional structured constraints."""

    model_config = ConfigDict(str_strip_whitespace=True)

    city: str = Field(..., min_length=1, max_length=100)
    start_date: date
    end_date: date
    travel_days: int | None = Field(default=None, ge=1, le=30)
    transportation: TransportationMode
    accommodation: AccommodationType
    preferences: list[str] = Field(default_factory=list, max_length=30)
    free_text_input: str = Field(default="", max_length=2000)
    travelers: int | None = Field(default=None, ge=1, le=20)
    budget_limit: Decimal | None = Field(default=None, gt=0, max_digits=10, decimal_places=2)
    currency: str | None = Field(default=None, pattern="^CNY$")
    must_visit: list[str] | None = Field(default=None, max_length=30)
    avoid_places: list[str] | None = Field(default=None, max_length=30)
    max_daily_walking_km: float | None = Field(default=None, gt=0, le=100)
    max_single_transport_minutes: int | None = Field(default=None, ge=1, le=720)

    @field_validator("preferences", "must_visit", "avoid_places", mode="before")
    @classmethod
    def normalize_name_lists(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        if not isinstance(values, list):
            raise ValueError("place and preference fields must be lists")
        result: list[str] = []
        seen: set[str] = set()
        for raw_value in values:
            if not isinstance(raw_value, str):
                raise ValueError("place and preference items must be strings")
            value = raw_value.strip()
            key = value.casefold()
            if value and key not in seen:
                result.append(value)
                seen.add(key)
        return result

    @model_validator(mode="after")
    def validate_dates_and_duration(self) -> "TripRequest":
        calculated_days = (self.end_date - self.start_date).days + 1
        if calculated_days < 1:
            raise ValueError("end_date must not be earlier than start_date")
        if calculated_days > 30:
            raise ValueError("trip duration must not exceed 30 days")
        if self.travel_days is not None and self.travel_days != calculated_days:
            raise ValueError("travel_days must match start_date and end_date")
        avoided = {name.casefold() for name in self.avoid_places or []}
        if any(name.casefold() in avoided for name in self.must_visit or []):
            raise ValueError("a place cannot be both required and avoided")
        self.travel_days = calculated_days
        return self


class POISearchRequest(BaseModel):
    """POI搜索请求"""
    keywords: str = Field(..., description="搜索关键词", example="故宫")
    city: str = Field(..., description="城市", example="北京")
    citylimit: bool = Field(default=True, description="是否限制在城市范围内")


class RouteRequest(BaseModel):
    """路线规划请求"""
    origin_address: str = Field(..., description="起点地址", example="北京市朝阳区阜通东大街6号")
    destination_address: str = Field(..., description="终点地址", example="北京市海淀区上地十街10号")
    origin_city: Optional[str] = Field(default=None, description="起点城市")
    destination_city: Optional[str] = Field(default=None, description="终点城市")
    route_type: str = Field(default="walking", description="路线类型: walking/driving/transit")


# ============ 响应模型 ============

class Location(BaseModel):
    """地理位置"""
    longitude: float = Field(..., description="经度")
    latitude: float = Field(..., description="纬度")


class Attraction(BaseModel):
    """景点信息"""
    name: str = Field(..., description="景点名称")
    address: str = Field(..., description="地址")
    location: Location = Field(..., description="经纬度坐标")
    visit_duration: int = Field(..., description="建议游览时间(分钟)")
    visit_start: time | None = None
    visit_end: time | None = None
    description: str = Field(..., description="景点描述")
    category: Optional[str] = Field(default="景点", description="景点类别")
    rating: Optional[float] = Field(default=None, description="评分")
    photos: Optional[List[str]] = Field(default_factory=list, description="景点图片URL列表")
    poi_id: Optional[str] = Field(default="", description="POI ID")
    image_url: Optional[str] = Field(default=None, description="图片URL")
    ticket_price: Optional[int] = Field(default=None, ge=0, description="每人门票价格(元)，未知为null")

    @model_validator(mode="after")
    def require_complete_visit_window(self) -> "Attraction":
        if (self.visit_start is None) != (self.visit_end is None):
            raise ValueError("visit_start and visit_end must be provided together")
        if self.visit_start is not None and (self.visit_start.tzinfo is not None or self.visit_end.tzinfo is not None):
            raise ValueError("visit times must be local times without timezone offsets")
        return self


class Meal(BaseModel):
    """餐饮信息"""
    type: str = Field(..., description="餐饮类型: breakfast/lunch/dinner/snack")
    name: str = Field(..., description="餐饮名称")
    address: Optional[str] = Field(default=None, description="地址")
    location: Optional[Location] = Field(default=None, description="经纬度坐标")
    description: Optional[str] = Field(default=None, description="描述")
    estimated_cost: Optional[int] = Field(default=None, ge=0, description="每人预估费用(元)，未知为null")


class Hotel(BaseModel):
    """酒店信息"""
    name: str = Field(..., description="酒店名称")
    address: str = Field(default="", description="酒店地址")
    location: Optional[Location] = Field(default=None, description="酒店位置")
    price_range: str = Field(default="", description="价格范围")
    rating: str = Field(default="", description="评分")
    distance: str = Field(default="", description="距离景点距离")
    type: str = Field(default="", description="酒店类型")
    estimated_cost: Optional[int] = Field(default=None, ge=0, description="每间每晚预估费用(元)，未知为null")


class RouteLeg(BaseModel):
    origin_name: str
    destination_name: str
    distance: Optional[float] = Field(default=None, ge=0, description="路线距离(米)")
    duration: Optional[int] = Field(default=None, ge=0, description="路线时间(秒)")
    route_type: Literal["walking", "driving", "transit"]
    status: Literal["available", "unavailable", "over_time_limit"]


class DayRoute(BaseModel):
    route_type: Literal["walking", "driving", "transit"]
    legs: List[RouteLeg] = Field(default_factory=list)
    total_distance: float = Field(default=0, ge=0)
    total_duration: int = Field(default=0, ge=0)
    is_complete: bool = True
    within_limits: bool = True
    warning_codes: List[Literal[
        "ROUTE_UNAVAILABLE", "SEGMENT_TIME_EXCEEDED",
        "DAILY_WALKING_EXCEEDED", "MATRIX_TRUNCATED",
    ]] = Field(default_factory=list)


class DayPlan(BaseModel):
    """单日行程"""
    date: str = Field(..., description="日期 YYYY-MM-DD")
    day_index: int = Field(..., description="第几天(从0开始)")
    description: str = Field(..., description="当日行程描述")
    transportation: str = Field(..., description="交通方式")
    transportation_cost: Optional[int] = Field(default=None, ge=0, description="当日每人交通预估费用(元)，未知为null")
    accommodation: str = Field(..., description="住宿")
    hotel: Optional[Hotel] = Field(default=None, description="推荐酒店")
    attractions: List[Attraction] = Field(default=[], description="景点列表")
    meals: List[Meal] = Field(default=[], description="餐饮列表")
    route: Optional[DayRoute] = Field(default=None, description="确定性路线优化摘要")


class WeatherInfo(BaseModel):
    """天气信息"""
    date: str = Field(..., description="日期 YYYY-MM-DD")
    day_weather: str = Field(default="", description="白天天气")
    night_weather: str = Field(default="", description="夜间天气")
    day_temp: Union[int, str] = Field(default=0, description="白天温度")
    night_temp: Union[int, str] = Field(default=0, description="夜间温度")
    wind_direction: str = Field(default="", description="风向")
    wind_power: str = Field(default="", description="风力")

    @field_validator('day_temp', 'night_temp', mode='before')
    @classmethod
    def parse_temperature(cls, v):
        """解析温度,移除°C等单位"""
        if isinstance(v, str):
            # 移除°C, ℃等单位符号
            v = v.replace('°C', '').replace('℃', '').replace('°', '').strip()
            try:
                return int(v)
            except ValueError:
                return 0
        return v


class BudgetUnknownItem(BaseModel):
    """A missing unit price that prevents an exact trip total."""

    category: Literal["attraction", "hotel", "meal", "transportation"]
    day_index: int = Field(ge=0)
    item_name: str


class Budget(BaseModel):
    """预算信息"""
    total_attractions: int = Field(default=0, ge=0, description="已知景点门票总费用")
    total_hotels: int = Field(default=0, ge=0, description="已知酒店总费用")
    total_meals: int = Field(default=0, ge=0, description="已知餐饮总费用")
    total_transportation: int = Field(default=0, ge=0, description="已知交通总费用")
    total: int = Field(default=0, ge=0, description="已知费用合计")
    currency: Literal["CNY"] = "CNY"
    travelers: int = Field(default=1, ge=1)
    rooms: int = Field(default=1, ge=1)
    accommodation_nights: int = Field(default=0, ge=0)
    is_complete: bool = True
    within_limit: Optional[bool] = None
    unknown_items: List[BudgetUnknownItem] = Field(default_factory=list)


class TripPlan(BaseModel):
    """旅行计划"""
    city: str = Field(..., description="目的地城市")
    start_date: str = Field(..., description="开始日期")
    end_date: str = Field(..., description="结束日期")
    days: List[DayPlan] = Field(..., description="每日行程")
    weather_info: List[WeatherInfo] = Field(default=[], description="天气信息")
    overall_suggestions: str = Field(..., description="总体建议")
    budget: Optional[Budget] = Field(default=None, description="预算信息")


class TripPlanResponse(BaseModel):
    """旅行计划响应"""
    success: bool = Field(..., description="是否成功")
    message: str = Field(default="", description="消息")
    data: Optional[TripPlan] = Field(default=None, description="旅行计划数据")
    plan_id: Optional[str] = Field(default=None, description="持久化计划ID")
    version: Optional[int] = Field(default=None, ge=1, description="持久化版本")


class TripPlanUpdateRequest(BaseModel):
    """Optimistic update: the caller must provide the version it read."""

    expected_version: int = Field(ge=1)
    data: TripPlan


class StoredTripPlanResponse(BaseModel):
    success: bool = True
    message: str = ""
    plan_id: str
    status: Literal["planning", "completed", "failed"]
    version: int = Field(ge=1)
    request: TripRequest
    data: Optional[TripPlan] = None
    error_code: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class POIInfo(BaseModel):
    """POI信息"""
    id: str = Field(..., description="POI ID")
    name: str = Field(..., description="名称")
    type: str = Field(..., description="类型")
    address: str = Field(..., description="地址")
    location: Location = Field(..., description="经纬度坐标")
    tel: Optional[str] = Field(default=None, description="电话")


class POISearchResponse(BaseModel):
    """POI搜索响应"""
    success: bool = Field(..., description="是否成功")
    message: str = Field(default="", description="消息")
    data: List[POIInfo] = Field(default=[], description="POI列表")


class RouteInfo(BaseModel):
    """路线信息"""
    distance: float = Field(..., description="距离(米)")
    duration: int = Field(..., description="时间(秒)")
    route_type: str = Field(..., description="路线类型")
    description: str = Field(..., description="路线描述")


class RouteResponse(BaseModel):
    """路线规划响应"""
    success: bool = Field(..., description="是否成功")
    message: str = Field(default="", description="消息")
    data: Optional[RouteInfo] = Field(default=None, description="路线信息")


class WeatherResponse(BaseModel):
    """天气查询响应"""
    success: bool = Field(..., description="是否成功")
    message: str = Field(default="", description="消息")
    data: List[WeatherInfo] = Field(default=[], description="天气信息")


# ============ 错误响应 ============

class ErrorResponse(BaseModel):
    """错误响应"""
    success: bool = Field(default=False, description="是否成功")
    message: str = Field(..., description="错误消息")
    error_code: Optional[str] = Field(default=None, description="错误代码")

    request_id: Optional[str] = Field(default=None, description="请求关联ID")
    detail: Optional[str] = Field(default=None, description="兼容现有前端的安全错误消息")
