import { ReactNode } from 'react'
import Sidebar from './Sidebar'

interface Props {
  children: ReactNode
  title?: string
  subtitle?: string
  actions?: ReactNode
}

export default function PageShell({ children, title, subtitle, actions }: Props) {
  return (
    <div className="flex min-h-screen bg-white">
      <Sidebar />
      <main className="flex-1 flex flex-col min-h-screen overflow-auto">
        {(title || actions) && (
          <header className="px-8 py-5 border-b border-dm-border flex items-center justify-between bg-white sticky top-0 z-10">
            <div>
              {title    && <h1 className="font-black text-xl text-dm-text tracking-tight">{title}</h1>}
              {subtitle && <p className="text-sm text-dm-muted font-light mt-0.5">{subtitle}</p>}
            </div>
            {actions && <div className="flex items-center gap-3">{actions}</div>}
          </header>
        )}
        <div className="flex-1 p-8 bg-white animate-fade-in">
          {children}
        </div>
      </main>
    </div>
  )
}
