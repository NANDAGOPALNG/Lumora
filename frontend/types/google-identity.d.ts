/** Minimal typings for the parts of Google Identity Services (GIS) Lumora uses. */

interface GoogleCredentialResponse {
  /** The Google ID token (JWT). Not a Lumora token; send it only to /auth/google. */
  credential: string;
  select_by?: string;
}

interface GoogleButtonConfig {
  type?: "standard" | "icon";
  theme?: "outline" | "filled_blue" | "filled_black";
  size?: "large" | "medium" | "small";
  text?: "signin_with" | "signup_with" | "continue_with" | "signin";
  shape?: "rectangular" | "pill";
  logo_alignment?: "left" | "center";
  width?: number;
  locale?: string;
}

interface Window {
  google?: {
    accounts: {
      id: {
        initialize: (config: {
          client_id: string;
          callback: (response: GoogleCredentialResponse) => void;
          ux_mode?: "popup" | "redirect";
          auto_select?: boolean;
        }) => void;
        renderButton: (parent: HTMLElement, options: GoogleButtonConfig) => void;
        disableAutoSelect: () => void;
      };
    };
  };
}
