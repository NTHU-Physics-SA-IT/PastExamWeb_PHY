from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


NTHU_STUDENT_ID_LENGTH = 9
NTHU_DEPARTMENT_CATALOG_SOURCE = (
    "https://registra.site.nthu.edu.tw/var/file/211/1211/img/816627133.pdf"
)
NTHU_DEPARTMENT_CATALOG_REVISION = "113.5.14"


class AffiliationStatus(str, Enum):
    PARSED = "parsed"
    UNKNOWN_SPECIAL = "unknown_special"


@dataclass(frozen=True)
class NthuDepartment:
    code: str
    name: str
    college_code: str
    college_name: str


@dataclass(frozen=True)
class NthuStudentAffiliation:
    status: AffiliationStatus
    admission_year: str | None = None
    college_code: str | None = None
    department_code: str | None = None
    program_code: str | None = None


def _departments(
    college_code: str,
    college_name: str,
    entries: tuple[tuple[str, str], ...],
) -> tuple[NthuDepartment, ...]:
    return tuple(
        NthuDepartment(
            code=code,
            name=name,
            college_code=college_code,
            college_name=college_name,
        )
        for code, name in entries
    )


# Authoritative backend catalog derived from the NTHU Registrar's current
# "100學年度起學生學號編碼原則" table (revision 113.5.14). Codes are the
# documented three-digit college+department portion, never the degree/program digit.
NTHU_DEPARTMENTS = (
    *_departments(
        "00",
        "跨院系所",
        (
            ("000", "清華學院學士班／跨系所招生"),
            ("001", "先進光源科技學位學程"),
            ("002", "學習科學研究所"),
            ("003", "跨院國際博士班學位學程"),
            ("004", "跨院國際碩士學位學程"),
            ("005", "智慧製造跨院高階主管碩士在職學位學程"),
            ("006", "清華學院國際學士班"),
            ("007", "藥品與醫材法規科學碩士在職學位學程"),
        ),
    ),
    *_departments(
        "01",
        "原子科學院",
        (
            ("010", "原子科學院學士班／跨系所招生"),
            ("011", "工程與系統科學系"),
            ("012", "生醫工程與環境科學系"),
            ("013", "核子工程與科學研究所"),
            ("014", "環境科技博士學位學程"),
            ("015", "分析與環境科學研究所"),
        ),
    ),
    *_departments(
        "02",
        "理學院",
        (
            ("020", "理學院跨系所招生"),
            ("021", "數學系"),
            ("022", "物理學系"),
            ("023", "化學系"),
            ("024", "統計學研究所"),
            ("025", "天文研究所"),
            ("026", "計算與建模科學研究所"),
        ),
    ),
    *_departments(
        "03",
        "工學院",
        (
            ("030", "工學院跨系所招生"),
            ("031", "材料科學工程學系"),
            ("032", "化學工程學系"),
            ("033", "動力機械工程學系"),
            ("034", "工業工程與工程管理學系"),
            ("035", "奈米工程與微系統研究所"),
            ("036", "工業工程與工程管理學系在職專班"),
            ("037", "工學院光電產業專班"),
            ("038", "生物醫學工程研究所"),
            ("039", "全球營運管理碩士雙聯學位學程"),
        ),
    ),
    *_departments(
        "13",
        "工學院",
        (
            ("131", "前瞻功能材料產業博士學位學程"),
            ("132", "資通訊熱流與電聲科技產業碩士專班"),
            ("133", "資通訊科技產品智慧設計與控制產業碩士專班"),
            ("134", "智慧生產與智能馬達電控產業碩士專班"),
            ("135", "資通訊科技產品智慧設計控制與熱流產業碩士專班"),
            ("136", "智慧生產與製造產業碩士專班"),
            ("137", "AI智慧製造與工業物聯網產業碩士專班"),
            ("138", "AI智慧製造與智慧物聯網產業碩士專班"),
            ("139", "電動載具先進智慧製造技術產業碩士專班"),
        ),
    ),
    *_departments(
        "23",
        "工學院",
        (
            ("231", "流體機械暨先進材料與智慧檢測產業碩士專班"),
            ("232", "智慧製造技術產業碩士專班"),
        ),
    ),
    *_departments(
        "04",
        "人文社會學院",
        (
            ("040", "人文社會學院跨系所招生"),
            ("041", "中國文學系"),
            ("042", "外國語文學系"),
            ("043", "歷史研究所"),
            ("044", "語言學研究所"),
            ("045", "社會學研究所"),
            ("046", "人類學研究所"),
            ("047", "哲學研究所"),
            ("048", "人文社會學院學士班"),
            ("049", "台灣文學研究所"),
        ),
    ),
    *_departments(
        "14",
        "人文社會學院",
        (
            ("141", "台灣教師在職進修專班"),
            ("142", "亞際文化研究碩士學位國際學程"),
            ("143", "華文文學研究所"),
            ("144", "人文社會學院國際生學士學位學程"),
            ("145", "華語文碩士學位學程"),
        ),
    ),
    *_departments(
        "06",
        "電機資訊學院",
        (
            ("060", "電機資訊學院學士班"),
            ("061", "電機工程學系"),
            ("062", "資訊工程學系"),
            ("063", "電子工程研究所"),
            ("064", "通訊工程研究所"),
            ("065", "資訊系統與應用研究所"),
            ("066", "光電工程研究所"),
            ("067", "電資院積體電路產業專班"),
            ("068", "電資院半導體元件及製程專班"),
            ("069", "電資院電力電子專班"),
        ),
    ),
    *_departments(
        "16",
        "電機資訊學院",
        (
            ("161", "光電博士學位學程"),
            ("162", "社群網路與人智計算國際研究生博士學位學程"),
            ("163", "積體電路設計與製程開發產業碩士專班"),
            ("164", "資訊安全研究所"),
        ),
    ),
    *_departments(
        "07",
        "科技管理學院",
        (
            ("070", "科技管理學院學士班"),
            ("071", "計量財務金融系"),
            ("072", "經濟學系"),
            ("073", "科技管理研究所"),
            ("074", "科技法律研究所"),
            ("075", "高階經營管理碩士在職專班"),
            ("076", "經營管理碩士在職專班"),
            ("077", "國際專業管理碩士班"),
            ("078", "服務科學研究所"),
            ("079", "財務金融碩士在職專班"),
        ),
    ),
    *_departments(
        "17",
        "科技管理學院",
        (
            ("171", "公共政策與管理碩士在職專班"),
            ("172", "高階經營管理深圳境外碩士在職專班"),
            ("173", "學士後法律學士學位學程"),
            ("174", "高階經營管理馬來西亞境外碩士在職專班"),
            ("175", "健康政策與經營管理碩士在職專班"),
            ("176", "高階經營管理雙聯碩士在職學位學程"),
        ),
    ),
    *_departments(
        "08",
        "生命科學院",
        (
            ("080", "生命科學院學士班／跨系所研究所"),
            ("081", "生命科學系"),
            ("082", "醫學科學系"),
            ("083", "跨領域神經科學博士學位學程"),
            ("084", "生技產業博士學位學程"),
            ("085", "智慧生醫博士學位學程"),
            ("086", "精準醫療博士學位學程"),
            ("088", "學士後醫學系"),
        ),
    ),
    *_departments(
        "09",
        "竹師教育學院",
        (
            ("090", "竹師教育學院學士班"),
            ("091", "教育與學習科技學系"),
            ("092", "教育與學習科技學系課程與教學碩士在職專班"),
            ("093", "教育與學習科技學系教育行政碩士在職專班"),
            ("095", "特殊教育學系"),
            ("096", "教育心理與諮商學系"),
            ("097", "教育心理與諮商碩士在職專班輔導諮商組"),
            ("098", "教育心理與諮商碩士在職專班工商心理組"),
            ("099", "英語教學系"),
        ),
    ),
    *_departments(
        "19",
        "竹師教育學院",
        (
            ("190", "跨領域STEAM教育碩士在職專班"),
            ("191", "幼兒教育學系"),
            ("192", "幼兒教育學系碩士在職專班"),
            ("193", "運動科學系"),
            ("194", "運動科學系碩士在職專班"),
            ("195", "環境與文化資源學系"),
            ("196", "環境與文化資源學系碩士在職專班"),
            ("197", "臺灣語言研究與教學研究所"),
            ("198", "數理教育研究所"),
            ("199", "數理教育研究所碩士在職專班"),
        ),
    ),
    *_departments(
        "29",
        "竹師教育學院",
        (
            ("291", "學習科學與科技研究所"),
            ("292", "學前特殊教育碩士在職學位學程"),
            ("293", "華德福教育碩士在職學位學程"),
            ("294", "心理與諮商新加坡境外碩士在職專班"),
            ("295", "竹師教育學院博士班"),
        ),
    ),
    *_departments(
        "59",
        "藝術學院",
        (
            ("590", "藝術學院學士班"),
            ("591", "音樂學系"),
            ("592", "音樂學系音樂碩士在職專班"),
            ("593", "藝術與設計學系"),
            ("594", "藝術與設計學系美勞教師碩士在職專班"),
            ("595", "科技藝術研究所"),
        ),
    ),
    *_departments(
        "50",
        "半導體研究學院",
        (
            ("501", "半導體研究學院碩士班"),
            ("502", "半導體研究學院博士班"),
        ),
    ),
    *_departments(
        "55",
        "台北政經學院",
        (("551", "台北政經學院政治經濟碩博士班"),),
    ),
)

_DEPARTMENTS_BY_CODE = {department.code: department for department in NTHU_DEPARTMENTS}
if len(_DEPARTMENTS_BY_CODE) != len(NTHU_DEPARTMENTS):  # pragma: no cover
    raise RuntimeError("NTHU department catalog contains duplicate codes")


def department_by_code(code: str | None) -> NthuDepartment | None:
    if code is None:
        return None
    return _DEPARTMENTS_BY_CODE.get(code)


def parse_nthu_student_affiliation(
    student_id: str | None,
) -> NthuStudentAffiliation:
    if (
        not isinstance(student_id, str)
        or len(student_id) != NTHU_STUDENT_ID_LENGTH
        or not student_id.isascii()
        or not student_id.isdigit()
    ):
        return NthuStudentAffiliation(status=AffiliationStatus.UNKNOWN_SPECIAL)

    return NthuStudentAffiliation(
        status=AffiliationStatus.PARSED,
        admission_year=student_id[0:3],
        college_code=student_id[3:5],
        department_code=student_id[3:6],
        program_code=student_id[3:7],
    )
