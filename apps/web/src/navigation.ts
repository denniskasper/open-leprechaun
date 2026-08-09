import {
  Activity,
  ArrowLeftRight,
  Coins,
  Gavel,
  Inbox,
  type LucideIcon,
  Scale,
  Shapes,
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

/**
 * The one place navigation is declared. A later ticket that adds a screen adds
 * its entry here and the sidebar, mobile sheet and active states follow.
 */
export const NAV_SECTIONS: NavSection[] = [
  {
    label: "Ledger",
    items: [
      { to: "/holdings", label: "Holdings", icon: Coins },
      { to: "/inbox", label: "Inbox", icon: Inbox },
      { to: "/transactions", label: "Transactions", icon: Scale },
      { to: "/transfers", label: "Transfers", icon: ArrowLeftRight },
      { to: "/instruments", label: "Instruments", icon: Shapes },
    ],
  },
  {
    label: "Settings",
    items: [
      { to: "/settings/platforms", label: "Platforms", icon: Vault },
      { to: "/settings/statutory", label: "Statutory", icon: Gavel },
    ],
  },
  {
    label: "System",
    items: [{ to: "/", label: "Health", icon: Activity }],
  },
];
