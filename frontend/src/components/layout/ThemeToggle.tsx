import { Monitor, Moon, Sun, type LucideIcon } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { strings } from '@/lib/strings'
import { useTheme, type ThemeMode } from '@/lib/theme'

const icons: Record<ThemeMode, LucideIcon> = { light: Sun, dark: Moon, system: Monitor }
const modes: ThemeMode[] = ['light', 'dark', 'system']

export function ThemeToggle() {
  const { mode, setMode } = useTheme()
  const Icon = icons[mode]
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" aria-label={strings.theme.label}>
          <Icon aria-hidden="true" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuRadioGroup value={mode} onValueChange={(value) => setMode(value as ThemeMode)}>
          {modes.map((item) => (
            <DropdownMenuRadioItem key={item} value={item}>
              {strings.theme[item]}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
