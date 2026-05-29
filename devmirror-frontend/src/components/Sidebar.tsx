import { ElementType, useEffect, useState } from 'react'
import { NavLink, useLocation, useNavigate } from 'react-router-dom'
import {
  LayoutDashboard, Sparkles, Code2, Target, Scale, Mail,
  Youtube, Terminal, LogOut, User, CalendarDays,
} from 'lucide-react'
import clsx from 'clsx'
import { getUserId, clearUserId, api, UserProfile } from '../api/client'

const PRIMARY_NAV = [
  { to: '/dashboard', icon: LayoutDashboard, label: 'Dashboard'   },
  { to: '/gmail',     icon: Mail,            label: 'Gmail Radar' },
  { to: '/youtube',   icon: Youtube,         label: 'YouTube'     },
  { to: '/calendar',  icon: CalendarDays,    label: 'Calendar'    },
  { to: '/coach',     icon: Terminal,        label: 'AI Coach'    },
]

const ANALYTICS_NAV = [
  { to: '/growth-report',  icon: Sparkles, label: 'Growth Report'  },
  { to: '/dsa',            icon: Code2,    label: 'DSA Progress'   },
  { to: '/focus',          icon: Target,   label: 'Focus Today'    },
  { to: '/learn-vs-build', icon: Scale,    label: 'Learn vs Build' },
]

function NavItem({ to, icon: Icon, label, active }: {
  to: string; icon: ElementType; label: string; active: boolean
}) {
  return (
    <NavLink
      to={to}
      className={clsx(
        'flex items-center gap-3 px-4 py-2.5 text-sm font-medium transition-colors duration-100',
        active
          ? 'bg-white/10 text-white border-l-2 border-white'
          : 'text-white/50 hover:text-white/80 hover:bg-white/5 border-l-2 border-transparent',
      )}
    >
      <Icon size={14} className={active ? 'text-white' : 'text-white/40'} />
      <span>{label}</span>
    </NavLink>
  )
}

export default function Sidebar() {
  const loc      = useLocation()
  const navigate = useNavigate()
  const userId   = getUserId()
  const [profile, setProfile] = useState<UserProfile | null>(null)

  useEffect(() => {
    if (userId) api.getUser(userId).then(setProfile).catch(() => {})
  }, [userId])

  function handleLogout() { clearUserId(); navigate('/') }

  return (
    <aside className="w-56 shrink-0 bg-[#1A1A14] flex flex-col h-screen sticky top-0">

      {/* Logo */}
      <div className="px-6 py-5 border-b border-white/10">
        <span className="font-black text-white text-lg tracking-tighter">DevMirror</span>
        <div className="text-[10px] text-white/30 font-mono mt-0.5">v2.0.0</div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 py-4 overflow-y-auto">
        <div className="px-4 mb-2">
          <p className="text-[10px] text-white/25 font-mono uppercase tracking-widest">Workspace</p>
        </div>
        {PRIMARY_NAV.map(({ to, icon, label }) => (
          <NavItem key={to} to={to} icon={icon} label={label} active={loc.pathname === to} />
        ))}

        <div className="px-4 mt-6 mb-2">
          <p className="text-[10px] text-white/25 font-mono uppercase tracking-widest">Analytics</p>
        </div>
        {ANALYTICS_NAV.map(({ to, icon, label }) => (
          <NavItem key={to} to={to} icon={icon} label={label} active={loc.pathname === to} />
        ))}
      </nav>

      {/* User */}
      <div className="px-4 py-4 border-t border-white/10 space-y-3">
        {userId ? (
          <>
            <div className="flex items-center gap-3">
              <div className="w-7 h-7 bg-white/15 flex items-center justify-center text-white text-xs font-bold shrink-0">
                {(profile?.name ?? profile?.email)?.[0]?.toUpperCase() ?? 'U'}
              </div>
              <div className="min-w-0 flex-1">
                <div className="text-xs font-medium text-white/80 truncate">{profile?.name ?? profile?.email ?? `User #${userId}`}</div>
                <div className="text-[10px] text-white/30 font-mono">Google connected</div>
              </div>
              <div className="w-1.5 h-1.5 rounded-full bg-dm-green shrink-0" />
            </div>
            <button
              onClick={handleLogout}
              className="w-full flex items-center gap-2 px-3 py-2 text-xs text-white/30 hover:text-white/60 transition-colors"
            >
              <LogOut size={12} /> Sign out
            </button>
          </>
        ) : (
          <NavLink
            to="/login"
            className="flex items-center gap-2 px-3 py-2.5 text-sm text-white/40 hover:text-white/70 transition-colors"
          >
            <User size={14} /> Sign in
          </NavLink>
        )}
      </div>
    </aside>
  )
}

