// 30-issue taxonomy with trade-off based intake questions (PRD section 7, step 2).
// Each issue defines a scalar axis 0..1 used for BOTH user intake and candidate
// stance placement, so alignment is a distance on the same axis.
// axis0 describes the position at 0.0, axis1 the position at 1.0.

export interface IssueOption {
  key: "A" | "B" | "C";
  label: string;
  scalar: number; // position on axis
}

export interface IssueDef {
  id: string;
  name: string;
  cluster: "economy" | "society" | "security" | "governance";
  voterQuestion: string; // the typical question voters ask
  tradeoffQuestion: string;
  axis0: string; // meaning of scalar 0
  axis1: string; // meaning of scalar 1
  options: IssueOption[];
}

export const ISSUES: IssueDef[] = [
  {
    id: "economy",
    name: "Economy",
    cluster: "economy",
    voterQuestion: "Will the economy grow?",
    tradeoffQuestion: "Which approach to economic growth is closest to your view?",
    axis0: "Growth through deregulation and tax cuts; markets lead",
    axis1: "Growth through public investment and industrial policy; government leads",
    options: [
      { key: "A", label: "Cut regulation and taxes; let markets drive growth", scalar: 0 },
      { key: "B", label: "Mix of market freedom and targeted public investment", scalar: 0.5 },
      { key: "C", label: "Major public investment and industrial policy", scalar: 1 },
    ],
  },
  {
    id: "inflation",
    name: "Inflation & Cost of Living",
    cluster: "economy",
    voterQuestion: "Will everyday expenses become more affordable?",
    tradeoffQuestion: "How should government fight high everyday costs?",
    axis0: "Reduce spending and regulation to lower prices",
    axis1: "Direct intervention: price controls, subsidies, anti-gouging rules",
    options: [
      { key: "A", label: "Cut government spending and regulation to cool prices", scalar: 0 },
      { key: "B", label: "Targeted relief (tax credits, subsidies) without price controls", scalar: 0.5 },
      { key: "C", label: "Directly cap or regulate prices in key sectors", scalar: 1 },
    ],
  },
  {
    id: "taxes",
    name: "Taxes",
    cluster: "economy",
    voterQuestion: "Should taxes increase, decrease, or stay the same?",
    tradeoffQuestion: "Which tax approach is closest to your view?",
    axis0: "Lower taxes across the board, including corporations and high earners",
    axis1: "Raise taxes on corporations and high earners to fund programs",
    options: [
      { key: "A", label: "Lower taxes broadly, including for businesses and top earners", scalar: 0 },
      { key: "B", label: "Keep roughly current levels; close loopholes", scalar: 0.5 },
      { key: "C", label: "Raise taxes on corporations and the wealthy", scalar: 1 },
    ],
  },
  {
    id: "jobs",
    name: "Jobs & Employment",
    cluster: "economy",
    voterQuestion: "Will there be more and better-paying jobs?",
    tradeoffQuestion: "How should government support jobs and wages?",
    axis0: "Reduce business costs and mandates so employers hire more",
    axis1: "Raise labor standards: higher minimum wage, stronger protections",
    options: [
      { key: "A", label: "Lower business costs and mandates to spur hiring", scalar: 0 },
      { key: "B", label: "Workforce training and incentives; modest wage rules", scalar: 0.5 },
      { key: "C", label: "Raise the minimum wage and strengthen job protections", scalar: 1 },
    ],
  },
  {
    id: "healthcare",
    name: "Healthcare",
    cluster: "society",
    voterQuestion: "How accessible and affordable is healthcare?",
    tradeoffQuestion: "Which healthcare direction is closest to your view?",
    axis0: "More private market competition; less government role",
    axis1: "Government-guaranteed coverage for everyone (single payer)",
    options: [
      { key: "A", label: "More competition and private options; less government", scalar: 0 },
      { key: "B", label: "Keep current mix; strengthen ACA and lower drug costs", scalar: 0.5 },
      { key: "C", label: "Move toward government-guaranteed universal coverage", scalar: 1 },
    ],
  },
  {
    id: "immigration",
    name: "Immigration",
    cluster: "security",
    voterQuestion: "How should immigration and border security be managed?",
    tradeoffQuestion: "Which immigration approach is closest to your view?",
    axis0: "Strict enforcement first: border security, more deportations, less legal immigration",
    axis1: "Expand legal pathways and protections; enforcement is secondary",
    options: [
      { key: "A", label: "Enforcement first: secure the border, increase deportations", scalar: 0 },
      { key: "B", label: "Both: stronger border security plus legal pathways", scalar: 0.5 },
      { key: "C", label: "Expand legal immigration and protections for undocumented residents", scalar: 1 },
    ],
  },
  {
    id: "crime",
    name: "Crime & Public Safety",
    cluster: "security",
    voterQuestion: "How should crime be reduced?",
    tradeoffQuestion: "Which public-safety approach is closest to your view?",
    axis0: "More police, tougher sentencing, stricter enforcement",
    axis1: "Invest in prevention, mental health, and criminal-justice reform",
    options: [
      { key: "A", label: "More police funding and tougher sentencing", scalar: 0 },
      { key: "B", label: "More police plus accountability and prevention programs", scalar: 0.5 },
      { key: "C", label: "Shift resources toward prevention and justice reform", scalar: 1 },
    ],
  },
  {
    id: "education",
    name: "Education",
    cluster: "society",
    voterQuestion: "How should schools and universities be funded and managed?",
    tradeoffQuestion: "Which education approach is closest to your view?",
    axis0: "School choice: vouchers, charters, parental control",
    axis1: "Invest in public schools; oppose diverting funds to private options",
    options: [
      { key: "A", label: "Expand school choice, vouchers, and charter schools", scalar: 0 },
      { key: "B", label: "Support both public schools and some choice options", scalar: 0.5 },
      { key: "C", label: "Increase public school funding; oppose vouchers", scalar: 1 },
    ],
  },
  {
    id: "housing",
    name: "Housing",
    cluster: "economy",
    voterQuestion: "How can housing become more affordable?",
    tradeoffQuestion: "Which housing approach is closest to your view?",
    axis0: "Deregulate: cut zoning rules so private builders add supply",
    axis1: "Public role: subsidized housing, tenant protections, rent stabilization",
    options: [
      { key: "A", label: "Cut zoning and permitting rules so builders add supply", scalar: 0 },
      { key: "B", label: "More supply plus targeted affordability programs", scalar: 0.5 },
      { key: "C", label: "Public/subsidized housing and stronger tenant protections", scalar: 1 },
    ],
  },
  {
    id: "climate",
    name: "Climate Change",
    cluster: "economy",
    voterQuestion: "What actions should be taken on climate?",
    tradeoffQuestion: "Which climate approach is closest to your view?",
    axis0: "Minimal mandates; prioritize economic growth and energy costs",
    axis1: "Aggressive action: rapid emissions cuts, major clean-energy mandates",
    options: [
      { key: "A", label: "Avoid mandates that raise costs; let markets adapt", scalar: 0 },
      { key: "B", label: "Steady transition with incentives, not hard mandates", scalar: 0.5 },
      { key: "C", label: "Aggressive emissions cuts and clean-energy requirements", scalar: 1 },
    ],
  },
  {
    id: "energy",
    name: "Energy",
    cluster: "economy",
    voterQuestion: "Should the focus be on fossil fuels, renewables, or both?",
    tradeoffQuestion: "Which energy strategy is closest to your view?",
    axis0: "Expand domestic oil, gas, and coal production",
    axis1: "Rapidly shift to renewables and phase down fossil fuels",
    options: [
      { key: "A", label: "Expand oil, gas, and domestic drilling", scalar: 0 },
      { key: "B", label: "All-of-the-above: fossil fuels, nuclear, and renewables", scalar: 0.5 },
      { key: "C", label: "Rapid transition to renewables; phase down fossil fuels", scalar: 1 },
    ],
  },
  {
    id: "debt_spending",
    name: "National Debt & Government Spending",
    cluster: "economy",
    voterQuestion: "How much should government spend or borrow?",
    tradeoffQuestion: "Which fiscal approach is closest to your view?",
    axis0: "Cut spending significantly to reduce deficits and debt",
    axis1: "Spend more on programs even if deficits rise; raise revenue later",
    options: [
      { key: "A", label: "Cut spending significantly to shrink the debt", scalar: 0 },
      { key: "B", label: "Balance targeted cuts with selective investment", scalar: 0.5 },
      { key: "C", label: "Prioritize program investment over deficit reduction", scalar: 1 },
    ],
  },
  {
    id: "social_security",
    name: "Social Security",
    cluster: "society",
    voterQuestion: "How should retirement benefits be funded?",
    tradeoffQuestion: "Which Social Security approach is closest to your view?",
    axis0: "Restructure: raise retirement age, private accounts, trim growth of benefits",
    axis1: "Expand benefits; fund by raising the payroll-tax cap on high earners",
    options: [
      { key: "A", label: "Restructure benefits (raise age, private options) for solvency", scalar: 0 },
      { key: "B", label: "Preserve current benefits; modest funding fixes", scalar: 0.5 },
      { key: "C", label: "Expand benefits; lift the payroll-tax cap", scalar: 1 },
    ],
  },
  {
    id: "medicare_medicaid",
    name: "Medicare & Medicaid",
    cluster: "society",
    voterQuestion: "Should public health programs change?",
    tradeoffQuestion: "Which direction for Medicare and Medicaid is closest to your view?",
    axis0: "Restrain growth: work requirements, block grants, private administration",
    axis1: "Expand eligibility and benefits for both programs",
    options: [
      { key: "A", label: "Restrain costs: eligibility requirements, private plans", scalar: 0 },
      { key: "B", label: "Maintain programs roughly as they are", scalar: 0.5 },
      { key: "C", label: "Expand eligibility and covered benefits", scalar: 1 },
    ],
  },
  {
    id: "abortion",
    name: "Abortion",
    cluster: "society",
    voterQuestion: "What legal protections or restrictions should exist?",
    tradeoffQuestion: "Which abortion policy is closest to your view?",
    axis0: "Significant restrictions or bans, with limited exceptions",
    axis1: "Broad legal protection; restore or codify Roe-level access nationally",
    options: [
      { key: "A", label: "Significant restrictions or a ban with limited exceptions", scalar: 0 },
      { key: "B", label: "Legal with limits (e.g., gestational thresholds); state-led", scalar: 0.5 },
      { key: "C", label: "Broad legal protection nationwide", scalar: 1 },
    ],
  },
  {
    id: "guns",
    name: "Gun Policy",
    cluster: "security",
    voterQuestion: "Should firearm laws change?",
    tradeoffQuestion: "Which gun policy is closest to your view?",
    axis0: "Protect gun rights; oppose new restrictions",
    axis1: "Stricter laws: universal background checks, assault-weapon limits",
    options: [
      { key: "A", label: "Protect gun rights; no new restrictions", scalar: 0 },
      { key: "B", label: "Targeted measures (background checks, red-flag laws)", scalar: 0.5 },
      { key: "C", label: "Broader restrictions including assault-weapon limits", scalar: 1 },
    ],
  },
  {
    id: "civil_rights",
    name: "Civil Rights",
    cluster: "society",
    voterQuestion: "How should equal rights and anti-discrimination laws evolve?",
    tradeoffQuestion: "Which civil-rights approach is closest to your view?",
    axis0: "Current laws suffice; limit new mandates on institutions",
    axis1: "Strengthen and expand anti-discrimination laws and enforcement",
    options: [
      { key: "A", label: "Existing protections are sufficient; avoid new mandates", scalar: 0 },
      { key: "B", label: "Enforce current laws more consistently", scalar: 0.5 },
      { key: "C", label: "Expand anti-discrimination protections and enforcement", scalar: 1 },
    ],
  },
  {
    id: "lgbtq",
    name: "LGBTQ+ Issues",
    cluster: "society",
    voterQuestion: "What legal protections and policies should exist?",
    tradeoffQuestion: "Which approach to LGBTQ+ policy is closest to your view?",
    axis0: "Limit recent policy changes; defer to states, parents, religious institutions",
    axis1: "Expand federal protections (e.g., Equality Act) for LGBTQ+ people",
    options: [
      { key: "A", label: "Defer to states, parents, and religious exemptions", scalar: 0 },
      { key: "B", label: "Maintain current protections without major changes", scalar: 0.5 },
      { key: "C", label: "Pass expanded federal anti-discrimination protections", scalar: 1 },
    ],
  },
  {
    id: "foreign_policy",
    name: "Foreign Policy",
    cluster: "security",
    voterQuestion: "How should the country engage internationally?",
    tradeoffQuestion: "Which foreign-policy posture is closest to your view?",
    axis0: "America-first: fewer commitments abroad, prioritize domestic interests",
    axis1: "Active global leadership: alliances, aid, and international institutions",
    options: [
      { key: "A", label: "Reduce foreign commitments; focus at home", scalar: 0 },
      { key: "B", label: "Selective engagement based on clear national interest", scalar: 0.5 },
      { key: "C", label: "Strong alliances and active global leadership", scalar: 1 },
    ],
  },
  {
    id: "national_security",
    name: "National Security",
    cluster: "security",
    voterQuestion: "How should threats be prevented and addressed?",
    tradeoffQuestion: "Which security approach is closest to your view?",
    axis0: "Expand surveillance and enforcement powers to prevent threats",
    axis1: "Protect civil liberties; require strict limits on security powers",
    options: [
      { key: "A", label: "Broader surveillance and enforcement tools", scalar: 0 },
      { key: "B", label: "Current powers with judicial oversight", scalar: 0.5 },
      { key: "C", label: "Stricter limits to protect civil liberties", scalar: 1 },
    ],
  },
  {
    id: "defense",
    name: "Military & Defense",
    cluster: "security",
    voterQuestion: "How much should be spent on defense?",
    tradeoffQuestion: "Which defense-spending view is closest to yours?",
    axis0: "Increase defense spending substantially",
    axis1: "Cut defense spending; shift funds to domestic priorities",
    options: [
      { key: "A", label: "Increase defense spending", scalar: 0 },
      { key: "B", label: "Keep spending roughly flat; spend smarter", scalar: 0.5 },
      { key: "C", label: "Reduce defense spending", scalar: 1 },
    ],
  },
  {
    id: "trade",
    name: "Trade & Tariffs",
    cluster: "economy",
    voterQuestion: "How should international trade be managed?",
    tradeoffQuestion: "Which trade approach is closest to your view?",
    axis0: "Protect domestic industry with tariffs and trade barriers",
    axis1: "Expand free trade and reduce tariffs",
    options: [
      { key: "A", label: "Use tariffs to protect domestic industries", scalar: 0 },
      { key: "B", label: "Targeted tariffs (e.g., strategic sectors) within open trade", scalar: 0.5 },
      { key: "C", label: "Reduce tariffs; expand free-trade agreements", scalar: 1 },
    ],
  },
  {
    id: "ai_tech",
    name: "AI & Technology",
    cluster: "governance",
    voterQuestion: "How should AI and emerging technologies be regulated?",
    tradeoffQuestion: "Which tech-regulation approach is closest to your view?",
    axis0: "Light touch: avoid rules that slow innovation",
    axis1: "Strong regulation: safety requirements, audits, liability for AI harms",
    options: [
      { key: "A", label: "Minimal regulation; prioritize innovation", scalar: 0 },
      { key: "B", label: "Targeted rules for high-risk uses only", scalar: 0.5 },
      { key: "C", label: "Comprehensive AI safety and accountability rules", scalar: 1 },
    ],
  },
  {
    id: "privacy",
    name: "Privacy & Data Security",
    cluster: "governance",
    voterQuestion: "How should personal data be protected?",
    tradeoffQuestion: "Which data-privacy approach is closest to your view?",
    axis0: "Industry self-regulation; avoid burdensome federal rules",
    axis1: "Strong federal privacy law with enforcement and private right of action",
    options: [
      { key: "A", label: "Let industry standards lead; minimal federal rules", scalar: 0 },
      { key: "B", label: "Federal baseline privacy law with moderate enforcement", scalar: 0.5 },
      { key: "C", label: "Strict federal privacy law with strong enforcement", scalar: 1 },
    ],
  },
  {
    id: "infrastructure",
    name: "Infrastructure",
    cluster: "economy",
    voterQuestion: "How should roads, bridges, transit, and broadband be improved?",
    tradeoffQuestion: "Which infrastructure approach is closest to your view?",
    axis0: "Private investment and user fees; limit federal spending",
    axis1: "Major federal investment in transit, roads, and broadband",
    options: [
      { key: "A", label: "Rely on private investment and public-private partnerships", scalar: 0 },
      { key: "B", label: "Moderate federal funding focused on repair", scalar: 0.5 },
      { key: "C", label: "Large federal investment including transit and broadband", scalar: 1 },
    ],
  },
  {
    id: "small_business",
    name: "Small Business",
    cluster: "economy",
    voterQuestion: "How should entrepreneurs and local businesses be supported?",
    tradeoffQuestion: "Which small-business approach is closest to your view?",
    axis0: "Cut regulations and taxes on small businesses",
    axis1: "Public support: grants, loans, and antitrust action against big firms",
    options: [
      { key: "A", label: "Cut small-business regulation and taxes", scalar: 0 },
      { key: "B", label: "Simplify rules plus targeted credit and support programs", scalar: 0.5 },
      { key: "C", label: "Public programs and antitrust enforcement to level the field", scalar: 1 },
    ],
  },
  {
    id: "labor",
    name: "Labor & Workers' Rights",
    cluster: "society",
    voterQuestion: "What protections should workers have?",
    tradeoffQuestion: "Which labor approach is closest to your view?",
    axis0: "Right-to-work; limit union power and workplace mandates",
    axis1: "Strengthen unions and worker protections (e.g., PRO Act)",
    options: [
      { key: "A", label: "Right-to-work laws; fewer union and workplace mandates", scalar: 0 },
      { key: "B", label: "Protect existing rights without major new mandates", scalar: 0.5 },
      { key: "C", label: "Strengthen union organizing rights and protections", scalar: 1 },
    ],
  },
  {
    id: "elections",
    name: "Voting & Election Laws",
    cluster: "governance",
    voterQuestion: "How should elections be conducted and secured?",
    tradeoffQuestion: "Which elections approach is closest to your view?",
    axis0: "Tighten rules: voter ID, limited mail voting, state control",
    axis1: "Expand access: automatic registration, mail voting, federal standards",
    options: [
      { key: "A", label: "Stricter rules: voter ID and limits on mail voting", scalar: 0 },
      { key: "B", label: "Balance access and security under state control", scalar: 0.5 },
      { key: "C", label: "Expand voting access with federal standards", scalar: 1 },
    ],
  },
  {
    id: "ethics",
    name: "Government Ethics & Corruption",
    cluster: "governance",
    voterQuestion: "How should transparency and accountability be improved?",
    tradeoffQuestion: "Which ethics-reform approach is closest to your view?",
    axis0: "Current ethics rules are adequate; enforce what exists",
    axis1: "Sweeping reform: stock-trading bans, lobbying limits, term limits",
    options: [
      { key: "A", label: "Enforce existing rules; avoid new restrictions", scalar: 0 },
      { key: "B", label: "Moderate reforms like disclosure improvements", scalar: 0.5 },
      { key: "C", label: "Sweeping reforms: trading bans, lobbying limits", scalar: 1 },
    ],
  },
  {
    id: "judiciary",
    name: "Judicial Appointments",
    cluster: "governance",
    voterQuestion: "What philosophy should judges bring to interpreting the law?",
    tradeoffQuestion: "Which judicial philosophy is closest to your view?",
    axis0: "Originalist/textualist judges who read the law narrowly",
    axis1: "Judges who read the Constitution as evolving with society",
    options: [
      { key: "A", label: "Originalist / textualist judges", scalar: 0 },
      { key: "B", label: "Pragmatic, case-by-case judges", scalar: 0.5 },
      { key: "C", label: "Living-constitution judges", scalar: 1 },
    ],
  },
];

export const ISSUE_MAP: Record<string, IssueDef> = Object.fromEntries(
  ISSUES.map((i) => [i.id, i])
);

export const CLUSTERS: Record<string, string[]> = ISSUES.reduce(
  (acc, i) => {
    (acc[i.cluster] ||= []).push(i.id);
    return acc;
  },
  {} as Record<string, string[]>
);
