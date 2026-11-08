import { Input } from "@/components/ui/input";

interface TokenFieldProps {
  id: string;
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  error?: string | null;
  onBlur?: () => void;
}

/**
 * Password-type input for a GitHub token. Kept only in the owning dialog's state and cleared right
 * after the request; autofill and spellcheck are off so nothing remembers or transmits it elsewhere.
 */
export function TokenField({ id, value, onChange, disabled, error, onBlur }: TokenFieldProps) {
  return (
    <div className="grid gap-2">
      <label htmlFor={id} className="text-sm font-medium">
        GitHub personal access token
      </label>
      <Input
        id={id}
        type="password"
        value={value}
        disabled={disabled}
        autoComplete="off"
        spellCheck={false}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${id}-error` : undefined}
        onChange={(event) => onChange(event.target.value)}
        onBlur={onBlur}
      />
      {error && (
        <p id={`${id}-error`} role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}
