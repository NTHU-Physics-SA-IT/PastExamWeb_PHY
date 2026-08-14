import { i18n } from '../i18n'

// English names are sourced from NTHU's current English academic-unit catalog
// (https://apply.nthu.edu.tw/en/department/list), current unit sites, and the
// Registrar's current/historical unit catalogs. Entries marked `curated` only
// supply product-required English coverage where no official wording was found.
// The Chinese name is retained so a reused or renamed provider code cannot be
// mistranslated.
const NTHU_DEPARTMENT_NAMES = Object.freeze({
  '000': { name: '清華學院學士班／跨系所招生', name_en: 'Tsing Hua Interdisciplinary Program' },
  '001': {
    name: '先進光源科技學位學程',
    name_en: 'Master and PhD Program for Science and Technology of Synchrotron Light Source',
  },
  '002': { name: '學習科學研究所', name_en: 'Institute of Learning Sciences' },
  '003': { name: '跨院國際博士班學位學程', name_en: 'International Intercollegiate PhD Program' },
  '004': { name: '跨院國際碩士學位學程', name_en: 'International Intercollegiate MS Program' },
  '005': {
    name: '智慧製造跨院高階主管碩士在職學位學程',
    name_en: 'AIMS Fellows Executive Master Program',
  },
  '006': { name: '清華學院國際學士班', name_en: 'International Bachelor Degree Program' },
  '007': {
    name: '藥品與醫材法規科學碩士在職學位學程',
    name_en: 'MS in Regulatory Affairs for Drugs & Medical Devices',
  },
  '010': {
    name: '原子科學院學士班／跨系所招生',
    name_en: 'Interdisciplinary Program of Nuclear Science',
  },
  '011': { name: '工程與系統科學系', name_en: 'Department of Engineering and System Science' },
  '012': {
    name: '生醫工程與環境科學系',
    name_en: 'Department of Biomedical Engineering and Environmental Sciences',
  },
  '013': { name: '核子工程與科學研究所', name_en: 'Institute of Nuclear Engineering and Science' },
  '014': {
    name: '環境科技博士學位學程',
    name_en: 'International Ph.D. Program in Environmental Science and Technology',
  },
  '015': {
    name: '分析與環境科學研究所',
    name_en: 'Institute of Analytical and Environmental Sciences',
  },
  '020': { name: '理學院跨系所招生', name_en: 'Interdisciplinary Program of Sciences' },
  '021': { name: '數學系', name_en: 'Department of Mathematics' },
  '022': { name: '物理學系', name_en: 'Department of Physics' },
  '023': { name: '化學系', name_en: 'Department of Chemistry' },
  '024': { name: '統計學研究所', name_en: 'Institute of Statistics' },
  '025': { name: '天文研究所', name_en: 'Institute of Astronomy' },
  '026': {
    name: '計算與建模科學研究所',
    name_en: 'Institute of Computational and Modeling Science',
  },
  '030': { name: '工學院跨系所招生', name_en: 'Interdisciplinary Program of Engineering' },
  '031': { name: '材料科學工程學系', name_en: 'Department of Materials Science and Engineering' },
  '032': { name: '化學工程學系', name_en: 'Department of Chemical Engineering' },
  '033': { name: '動力機械工程學系', name_en: 'Department of Power Mechanical Engineering' },
  '034': {
    name: '工業工程與工程管理學系',
    name_en: 'Department of Industrial Engineering and Engineering Management',
  },
  '035': {
    name: '奈米工程與微系統研究所',
    name_en: 'Institute of NanoEngineering and MicroSystems',
  },
  '036': {
    name: '工業工程與工程管理學系在職專班',
    name_en: 'Department of Industrial Engineering and Engineering Management',
  },
  '037': {
    name: '工學院光電產業專班',
    name_en: "Optoelectronics Industry Master's Program, College of Engineering",
  },
  '038': { name: '生物醫學工程研究所', name_en: 'Institute of Biomedical Engineering' },
  '039': {
    name: '全球營運管理碩士雙聯學位學程',
    name_en: 'Dual Master Program for Global Operation Management',
  },
  '040': {
    name: '人文社會學院跨系所招生',
    name_en: 'Interdisciplinary Admissions, College of Humanities and Social Sciences',
  },
  '041': { name: '中國文學系', name_en: 'Department of Chinese Literature' },
  '042': { name: '外國語文學系', name_en: 'Department of Foreign Languages and Literature' },
  '043': { name: '歷史研究所', name_en: 'Institute of History' },
  '044': { name: '語言學研究所', name_en: 'Institute of Linguistics' },
  '045': { name: '社會學研究所', name_en: 'Institute of Sociology' },
  '046': { name: '人類學研究所', name_en: 'Institute of Anthropology' },
  '047': { name: '哲學研究所', name_en: 'Institute of Philosophy' },
  '048': {
    name: '人文社會學院學士班',
    name_en: 'Interdisciplinary Program of Humanities and Social Sciences',
  },
  '049': { name: '台灣文學研究所', name_en: 'Institute of Taiwan Literature' },
  141: {
    name: '台灣教師在職進修專班',
    name_en: "Master's Degree Program of Taiwan Studies for In-service Teachers",
  },
  142: {
    name: '亞際文化研究碩士學位國際學程',
    name_en: "International Master's Program in Inter-Asia Cultural Studies",
  },
  143: { name: '華文文學研究所', name_en: 'Institute of Sinophone Studies' },
  144: {
    name: '人文社會學院國際生學士學位學程',
    name_en: 'International Undergraduate Program of College of Humanities and Social Sciences',
  },
  145: { name: '華語文碩士學位學程', name_en: "Master's Program in Chinese Language and Culture" },
  131: {
    name: '前瞻功能材料產業博士學位學程',
    name_en: 'Ph. D. Program in Prospective Functional Materials Industry',
  },
  132: {
    name: '資通訊熱流與電聲科技產業碩士專班',
    name_en: "Industrial Master's Program in ICT Thermal and Electroacoustic Technologies",
  },
  133: {
    name: '資通訊科技產品智慧設計與控制產業碩士專班',
    name_en: "Industrial Master's Program in Intelligent Design and Control of ICT Products",
  },
  134: {
    name: '智慧生產與智能馬達電控產業碩士專班',
    name_en: "Industrial Master's Program in Intelligent Production and Smart Motor Control",
  },
  135: {
    name: '資通訊科技產品智慧設計控制與熱流產業碩士專班',
    name_en:
      "Industrial Master's Program in Intelligent Design, Control, and Thermal Technologies for ICT Products",
  },
  136: {
    name: '智慧生產與製造產業碩士專班',
    name_en: "Industrial Master's Program in Intelligent Production and Manufacturing",
  },
  137: {
    name: 'AI智慧製造與工業物聯網產業碩士專班',
    name_en:
      "Industrial Master's Program in AI Smart Manufacturing and the Industrial Internet of Things",
  },
  138: {
    name: 'AI智慧製造與智慧物聯網產業碩士專班',
    name_en:
      "Industrial Master's Program in AI Smart Manufacturing and the Intelligent Internet of Things",
  },
  139: {
    name: '電動載具先進智慧製造技術產業碩士專班',
    name_en:
      "Industrial Master's Program in Advanced Intelligent Manufacturing Technologies for Electric Vehicles",
  },
  231: {
    name: '流體機械暨先進材料與智慧檢測產業碩士專班',
    name_en:
      "Industrial Master's Program in Fluid Machinery, Advanced Materials, and Intelligent Inspection",
  },
  232: {
    name: '智慧製造技術產業碩士專班',
    name_en: 'Industrial Technology Graduate Program of Intelligent Manufacturing Technology',
  },
  '060': {
    name: '電機資訊學院學士班',
    name_en: 'Interdisciplinary Program of Electrical Engineering and Computer Science',
  },
  '061': { name: '電機工程學系', name_en: 'Department of Electrical Engineering' },
  '062': { name: '資訊工程學系', name_en: 'Department of Computer Science' },
  '063': { name: '電子工程研究所', name_en: 'Institute of Electronics Engineering' },
  '064': { name: '通訊工程研究所', name_en: 'Institute of Communications Engineering' },
  '065': {
    name: '資訊系統與應用研究所',
    name_en: 'Institute of Information Systems and Applications',
  },
  '066': { name: '光電工程研究所', name_en: 'Institute of Photonics Technologies' },
  '067': {
    name: '電資院積體電路產業專班',
    name_en: 'Industrial Technology R&D Master Program on IC Design',
  },
  '068': {
    name: '電資院半導體元件及製程專班',
    name_en:
      'Industrial Technology R&D Master Program on Semiconductor Devices and Manufacturing Process',
  },
  '069': {
    name: '電資院電力電子專班',
    name_en: 'Industrial Technology R&D Master Program on Power Electronics',
  },
  161: { name: '光電博士學位學程', name_en: 'International Ph.D. Program in Photonics' },
  162: {
    name: '社群網路與人智計算國際研究生博士學位學程',
    name_en: 'Social Networks and Human-Centered Computing Program',
  },
  163: {
    name: '積體電路設計與製程開發產業碩士專班',
    name_en: "Industrial Master's Program in Integrated Circuit Design and Process Development",
  },
  164: { name: '資訊安全研究所', name_en: 'Institute of Information Security' },
  '070': {
    name: '科技管理學院學士班',
    name_en: 'Interdisciplinary Program of Management and Technology',
  },
  '071': { name: '計量財務金融系', name_en: 'Department of Quantitative Finance' },
  '072': { name: '經濟學系', name_en: 'Department of Economics' },
  '073': { name: '科技管理研究所', name_en: 'Institute of Technology Management' },
  '074': { name: '科技法律研究所', name_en: 'Institute of Law for Science and Technology' },
  '075': {
    name: '高階經營管理碩士在職專班',
    name_en: 'Executive Master of Business Administration',
  },
  '076': { name: '經營管理碩士在職專班', name_en: 'Master of Business Administration' },
  '077': { name: '國際專業管理碩士班', name_en: 'International Master of Business Administration' },
  '078': { name: '服務科學研究所', name_en: 'Institute of Service Science' },
  '079': { name: '財務金融碩士在職專班', name_en: 'Master of Finance and Banking' },
  171: {
    name: '公共政策與管理碩士在職專班',
    name_en: 'Master Program of Public Policy and Management',
  },
  172: {
    name: '高階經營管理深圳境外碩士在職專班',
    name_en: 'Overseas Executive Master of Business Administration (Shenzhen)',
  },
  173: {
    name: '學士後法律學士學位學程',
    name_en: "Post-Baccalaureate Bachelor's Degree Program in Law",
  },
  174: {
    name: '高階經營管理馬來西亞境外碩士在職專班',
    name_en: 'Overseas Executive Master of Business Administration (Malaysia)',
  },
  175: {
    name: '健康政策與經營管理碩士在職專班',
    name_en: 'Master Program of Health Policy and Business Administration',
  },
  176: {
    name: '高階經營管理雙聯碩士在職學位學程',
    name_en: 'NTHU-UTA Dual EMBA Degree Program',
  },
  '080': {
    name: '生命科學院學士班／跨系所研究所',
    name_en: 'Interdisciplinary Program of Life Sciences and Medicine',
  },
  '081': { name: '生命科學系', name_en: 'Department of Life Science' },
  '082': { name: '醫學科學系', name_en: 'Department of Medical Science' },
  '083': {
    name: '跨領域神經科學博士學位學程',
    name_en: 'International Ph.D. Program in Interdisciplinary Neuroscience',
  },
  '084': { name: '生技產業博士學位學程', name_en: 'Ph.D. Program in Bioindustrial Technology' },
  '085': {
    name: '智慧生醫博士學位學程',
    name_en: 'Ph.D. Program in Biomedical Artificial Intelligence',
  },
  '086': { name: '精準醫療博士學位學程', name_en: 'Precision Medicine Ph.D. Program' },
  '088': { name: '學士後醫學系', name_en: 'School of Medicine' },
  '090': { name: '竹師教育學院學士班', name_en: 'Interdisciplinary Program of Education' },
  '091': { name: '教育與學習科技學系', name_en: 'Department of Education and Learning Technology' },
  '092': {
    name: '教育與學習科技學系課程與教學碩士在職專班',
    name_en:
      "In-service Master's Program in Curriculum and Instruction, Department of Education and Learning Technology",
  },
  '093': {
    name: '教育與學習科技學系教育行政碩士在職專班',
    name_en:
      "In-service Master's Program in Educational Administration, Department of Education and Learning Technology",
  },
  '095': { name: '特殊教育學系', name_en: 'Department of Special Education' },
  '096': {
    name: '教育心理與諮商學系',
    name_en: 'Department of Educational Psychology and Counseling',
  },
  '097': {
    name: '教育心理與諮商碩士在職專班輔導諮商組',
    name_en:
      "In-service Master's Program in Counseling, Department of Educational Psychology and Counseling",
  },
  '098': {
    name: '教育心理與諮商碩士在職專班工商心理組',
    name_en:
      "In-service Master's Program in Industrial and Organizational Psychology, Department of Educational Psychology and Counseling",
  },
  '099': { name: '英語教學系', name_en: 'Department of English Instruction' },
  190: {
    name: '跨領域STEAM教育碩士在職專班',
    name_en: 'Master Program in Interdisciplinary STEAM Education',
  },
  191: { name: '幼兒教育學系', name_en: 'Department of Early Childhood Education' },
  192: {
    name: '幼兒教育學系碩士在職專班',
    name_en: 'Master Program in Early Childhood Education for In-service Practitioners',
  },
  193: { name: '運動科學系', name_en: 'Department of Kinesiology' },
  194: {
    name: '運動科學系碩士在職專班',
    name_en: 'In-Service Master Program of Kinesiology',
  },
  195: {
    name: '環境與文化資源學系',
    name_en: 'Department of Environmental and Cultural Resources',
  },
  196: {
    name: '環境與文化資源學系碩士在職專班',
    name_en:
      'In-service Master Program of Community Development and Social Studies, Department of Environmental and Cultural Resources',
  },
  197: {
    name: '臺灣語言研究與教學研究所',
    name_en: 'Institute of Taiwan Languages and Language Teaching',
  },
  198: {
    name: '數理教育研究所',
    name_en: 'Graduate Institute of Mathematics and Science Education',
  },
  199: {
    name: '數理教育研究所碩士在職專班',
    name_en: 'Mathematics & Science Education Master Inservice Program',
  },
  291: { name: '學習科學與科技研究所', name_en: 'Institute of Learning Sciences and Technologies' },
  292: {
    name: '學前特殊教育碩士在職學位學程',
    name_en: 'Master Program in Early Childhood Special Education',
  },
  293: {
    name: '華德福教育碩士在職學位學程',
    name_en: 'Master’s Program in Waldorf Education',
  },
  294: {
    name: '心理與諮商新加坡境外碩士在職專班',
    name_en: 'Master’s Program in Psychology and Counseling, Singapore',
  },
  295: { name: '竹師教育學院博士班', name_en: 'Ph.D. Program in Education Sciences' },
  590: { name: '藝術學院學士班', name_en: 'Interdisciplinary Program of Technology and Art' },
  591: { name: '音樂學系', name_en: 'Department of Music' },
  592: { name: '音樂學系音樂碩士在職專班', name_en: 'In-service Master Program in Music' },
  593: { name: '藝術與設計學系', name_en: 'Department of Arts and Design' },
  594: {
    name: '藝術與設計學系美勞教師碩士在職專班',
    name_en: 'In-service Master Program of Arts Education for Teachers',
  },
  595: { name: '科技藝術研究所', name_en: 'Graduate Institute of Art and Technology' },
  501: {
    name: '半導體研究學院碩士班',
    name_en: "Master's Program, College of Semiconductor Research",
  },
  502: {
    name: '半導體研究學院博士班',
    name_en: 'Doctoral Program, College of Semiconductor Research',
  },
  551: {
    name: '台北政經學院政治經濟碩博士班',
    name_en: 'Master’s and Ph.D. Program in Political Economy',
  },
})

const OFFICIAL_HISTORICAL_NTHU_DEPARTMENT_CODES = new Set(['067', '068', '069'])

const CURATED_NTHU_DEPARTMENT_CODES = new Set([
  '037',
  '040',
  '132',
  '133',
  '134',
  '135',
  '136',
  '137',
  '138',
  '139',
  '163',
  '173',
  '231',
  '092',
  '093',
  '097',
  '098',
  '501',
  '502',
])

export const NTHU_DEPARTMENT_PRESENTATIONS = Object.freeze(
  Object.fromEntries(
    Object.entries(NTHU_DEPARTMENT_NAMES).map(([code, presentation]) => [
      code,
      Object.freeze({
        ...presentation,
        provenance: CURATED_NTHU_DEPARTMENT_CODES.has(code)
          ? 'curated'
          : OFFICIAL_HISTORICAL_NTHU_DEPARTMENT_CODES.has(code)
            ? 'official-historical'
            : 'official-current',
      }),
    ])
  )
)

const NTHU_COLLEGE_PRESENTATIONS = Object.freeze({
  '00': { name: '跨院系所', name_en: 'Interdisciplinary Programs' },
  '01': { name: '原子科學院', name_en: 'College of Nuclear Science' },
  '02': { name: '理學院', name_en: 'College of Science' },
  '03': { name: '工學院', name_en: 'College of Engineering' },
  '04': { name: '人文社會學院', name_en: 'College of Humanities and Social Sciences' },
  '06': {
    name: '電機資訊學院',
    name_en: 'College of Electrical Engineering and Computer Science',
  },
  '07': { name: '科技管理學院', name_en: 'College of Technology Management' },
  '08': { name: '生命科學院', name_en: 'College of Life Science' },
  '09': { name: '竹師教育學院', name_en: 'College of Education' },
  13: { name: '工學院', name_en: 'College of Engineering' },
  14: { name: '人文社會學院', name_en: 'College of Humanities and Social Sciences' },
  16: {
    name: '電機資訊學院',
    name_en: 'College of Electrical Engineering and Computer Science',
  },
  17: { name: '科技管理學院', name_en: 'College of Technology Management' },
  19: { name: '竹師教育學院', name_en: 'College of Education' },
  23: { name: '工學院', name_en: 'College of Engineering' },
  29: { name: '竹師教育學院', name_en: 'College of Education' },
  50: { name: '半導體研究學院', name_en: 'College of Semiconductor Research' },
  55: {
    name: '台北政經學院',
    name_en: 'Taipei School of Economics and Political Science',
  },
  59: { name: '藝術學院', name_en: 'College of Arts' },
})

export function localizedNthuDepartmentName(department, catalog = []) {
  const code = department?.code || department?.department_code
  const catalogEntry = catalog.find((item) => item?.code === code)
  const canonicalName = department?.department_name || department?.name || catalogEntry?.name || ''
  if (i18n.global.locale.value !== 'en') return canonicalName

  const presentation = NTHU_DEPARTMENT_PRESENTATIONS[code]
  return presentation?.name === canonicalName ? presentation.name_en : canonicalName
}

export function localizedNthuCollegeName(department) {
  const canonicalName = department?.canonical_college_name || department?.college_name || ''
  if (i18n.global.locale.value !== 'en') return canonicalName

  const presentation = NTHU_COLLEGE_PRESENTATIONS[department?.college_code]
  return presentation?.name === canonicalName ? presentation.name_en : canonicalName
}

export function localizedNthuDepartmentOptions(departments) {
  return departments.map((department) => ({
    ...department,
    name: localizedNthuDepartmentName(department),
    canonical_name: department.name,
    college_name: localizedNthuCollegeName(department),
    canonical_college_name: department.college_name,
  }))
}
