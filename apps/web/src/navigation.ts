import {
  Activity,
  ArrowLeftRight,
  CalendarClock,
  CalendarRange,
  ChartLine,
  Coins,
  Download,
  FileOutput,
  Gavel,
  Inbox,
  KeyRound,
  type LucideIcon,
  Scale,
  Shapes,
  ShieldCheck,
  Split,
  Vault,
} from "lucide-react";

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
}

export interface NavSection {
  label: string;
  items: NavItem[];
}

// Never empty: a bare /settings has to have somewhere to go.
const SETTINGS_PANELS: [NavItem, ...NavItem[]] = [
  { to: "/settings/platforms", label: "Platforms", icon: Vault },
  { to: "/settings/connections", label: "Connections", icon: KeyRound },
  { to: "/settings/statutory", label: "Statutory", icon: Gavel },
  { to: "/settings/scheduled-tasks", label: "Scheduled tasks", icon: CalendarClock },
  { to: "/settings/security", label: "Security", icon: ShieldCheck },
];

/**
 * Where a bare `/settings` lands. Settings has no index page — a list of
 * links to the panels would only repeat the sidebar — so it opens its first
 * panel instead.
 */
export const SETTINGS_INDEX = SETTINGS_PANELS[0].to;

/**
 * The one place navigation is declared. A later ticket that adds a screen adds
 * its entry here and the sidebar, mobile sheet and active states follow.
 */
export const NAV_SECTIONS: NavSection[] = [
  {
    label: "Ledger",
    items: [
      { to: "/holdings", label: "Holdings", icon: Coins },
      { to: "/portfolio", label: "Portfolio", icon: ChartLine },
      { to: "/inbox", label: "Inbox", icon: Inbox },
      { to: "/transactions", label: "Transactions", icon: Scale },
      { to: "/transfers", label: "Transfers", icon: ArrowLeftRight },
      { to: "/imports", label: "Imports", icon: Download },
      { to: "/instruments", label: "Instruments", icon: Shapes },
      { to: "/corporate-actions", label: "Corporate actions", icon: Split },
      { to: "/export", label: "Export", icon: FileOutput },
    ],
  },
  {
    label: "Tax",
    items: [{ to: "/tax/overview", label: "Multi-year overview", icon: CalendarRange }],
  },
  { label: "Settings", items: SETTINGS_PANELS },
  {
    label: "System",
    items: [{ to: "/", label: "Health", icon: Activity }],
  },
];
