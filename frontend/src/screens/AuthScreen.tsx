import React, { useState } from "react";
import { api, isApiError, friendlyMessage } from "../api/client";
import PasswordInput from "../components/PasswordInput";
import type { AuthRequest } from "../api/types";
interface AuthScreenProps {
  onAuthenticated: (username: string, isAdmin?: boolean) => void;
}

export default function AuthScreen({ onAuthenticated }: AuthScreenProps) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [pending, setPending] = useState(false);

  const [errors, setErrors] = useState<{
    username?: string;
    password?: string;
    confirmPassword?: string;
    form?: string;
  }>({});

  const validateAll = (): boolean => {
    let isValid = true;
    const next: typeof errors = {};
    const u = username.trim();
    if (mode === "login") {
      if (!u) {
        next.username = "Username is required.";
        isValid = false;
      }
      if (!password) {
        next.password = "Password is required.";
        isValid = false;
      }
    } else {
      if (!u) {
        next.username = "Username is required.";
        isValid = false;
      } else if (!/^[A-Za-z0-9_.-]{3,32}$/.test(u)) {
        next.username = "Use 3–32 letters, numbers, dots, dashes or underscores.";
        isValid = false;
      }
      if (!password) {
        next.password = "Password is required.";
        isValid = false;
      } else if (password.length < 8 || password.length > 128) {
        next.password = "Password must be 8–128 characters.";
        isValid = false;
      }
      if (!confirmPassword) {
        next.confirmPassword = "Confirm your password.";
        isValid = false;
      } else if (password !== confirmPassword) {
        next.confirmPassword = "Passwords do not match.";
        isValid = false;
      }
    }
    setErrors(next);
    return isValid;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!validateAll()) return;

    setPending(true);
    setErrors({});

    try {
      const body: AuthRequest = { username: username.trim(), password };
      const resp = mode === "login" ? await api.login(body) : await api.register(body);
      onAuthenticated(resp.username, resp.is_admin);
    } catch (err: unknown) {
      if (isApiError(err)) {
        if (err.code === "INVALID_USERNAME" || err.code === "USERNAME_TAKEN") {
          setErrors({ username: friendlyMessage(err.code, err.message) });
        } else if (err.code === "INVALID_PASSWORD") {
          setErrors({ password: friendlyMessage(err.code, err.message) });
        } else {
          setErrors({ form: friendlyMessage(err.code, err.message) });
        }
      } else {
        setErrors({ form: "An unexpected error occurred." });
      }
    } finally {
      setPending(false);
    }
  };

  return (
    <div className="auth-panel panel">
      <h2>{mode === "login" ? "Sign in" : "Create account"}</h2>
      {errors.form && (
        <div className="msg error" role="alert">
          {errors.form}
        </div>
      )}

      <form onSubmit={handleSubmit} className="vstack mt" noValidate>
        <div className="field">
          <label htmlFor="auth-username">Username</label>
          <input
            id="auth-username"
            type="text"
            value={username}
            onChange={(e) => {
              setUsername(e.target.value);
              if (errors.username) setErrors((prev) => ({ ...prev, username: undefined }));
            }}
            autoComplete="username"
            autoCapitalize="none"
            autoCorrect="off"
            spellCheck={false}
            aria-invalid={!!errors.username}
            aria-describedby={errors.username ? "auth-username-error" : undefined}
            disabled={pending}
          />
          {errors.username && (
            <div id="auth-username-error" className="field-error">
              {errors.username}
            </div>
          )}
        </div>

        <div className="field mt">
          <label htmlFor="auth-password">Password</label>
          <PasswordInput
            id="auth-password"
            value={password}
            onChange={(e) => {
              setPassword(e.target.value);
              if (errors.password) setErrors((prev) => ({ ...prev, password: undefined }));
            }}
            autoComplete={mode === "login" ? "current-password" : "new-password"}
            visible={showPassword}
            onToggleVisible={() => setShowPassword(!showPassword)}
            invalid={!!errors.password}
            describedBy={errors.password ? "auth-password-error" : undefined}
            disabled={pending}
          />
          {errors.password && (
            <div id="auth-password-error" className="field-error">
              {errors.password}
            </div>
          )}
        </div>

        {mode === "register" && (
          <div className="field mt">
            <label htmlFor="auth-confirm">Confirm password</label>
            <PasswordInput
              id="auth-confirm"
              value={confirmPassword}
              onChange={(e) => {
                setConfirmPassword(e.target.value);
                if (errors.confirmPassword) setErrors((prev) => ({ ...prev, confirmPassword: undefined }));
              }}
              autoComplete="new-password"
              visible={showPassword}
              invalid={!!errors.confirmPassword}
              describedBy={errors.confirmPassword ? "auth-confirm-error" : undefined}
              disabled={pending}
            />
            {errors.confirmPassword && (
              <div id="auth-confirm-error" className="field-error">
                {errors.confirmPassword}
              </div>
            )}
          </div>
        )}

        <div className="auth-actions mt-lg">
          <button type="submit" className="primary auth-submit-btn" disabled={pending}>
            {mode === "login" ? "Sign in" : "Create account"}
          </button>
        </div>
      </form>

      <div className="center mt-lg">
        <button
          type="button"
          className="link-button"
          onClick={() => {
            setMode(mode === "login" ? "register" : "login");
            setErrors({});
            setUsername("");
            setPassword("");
            setConfirmPassword("");
          }}
          disabled={pending}
        >
          {mode === "login" ? "Need an account? Create one" : "Already have an account? Sign in"}
        </button>
      </div>
    </div>
  );
}
