"use client";

import { Monitor, Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { cn } from "@/lib/utils";

const options = [
  { value: "light", label: "Light", icon: Sun },
  { value: "dark", label: "Dark", icon: Moon },
  { value: "system", label: "System", icon: Monitor },
] as const;

export function ThemeSelector() {
  const { theme = "system", setTheme } = useTheme();

  return (
    <div role="radiogroup" aria-label="Theme" className="grid max-w-md grid-cols-3 gap-3">
      {options.map(({ value, label, icon: Icon }) => {
        const selected = theme === value;
        return (
          <button
            key={value}
            type="button"
            role="radio"
            aria-checked={selected}
            onClick={() => setTheme(value)}
            className={cn(
              "flex flex-col items-center gap-2 rounded-lg border bg-card px-3 py-4 text-sm font-medium transition-colors hover:bg-accent/60",
              selected && "border-foreground",
            )}
          >
            <Icon className="size-5 text-muted-foreground" aria-hidden />
            {label}
          </button>
        );
      })}
    </div>
  );
}
