import React, { useState } from "react";
import { api, isApiError, friendlyMessage } from "../api/client";
import PasswordInput from "../components/PasswordInput";
import type { AuthRequest } from "../api/types";
import { authCard, btn, field, fieldError, fieldHint, fieldLabel, msg, pageSub, pageTitle, spinnerOnFill, submitFull, textLink } from "../ui";

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

  const isLogin = mode === "login";

  return (
    <div className={authCard}>
      <h1 className={pageTitle}>{isLogin ? "Login" : "Create account"}</h1>
      <p className={pageSub}>
        {isLogin
          ? "Enter your username and password to continue."
          : "Choose a username and password for your new account."}
      </p>

      {errors.form && (
        <div className={`${msg.error} mt-5`} role="alert">
          {errors.form}
        </div>
      )}

      <form onSubmit={handleSubmit} className="flex flex-col gap-4 mt-6" noValidate>
        <div className={field}>
          <label className={fieldLabel} htmlFor="auth-username">Username</label>
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
            aria-describedby={
              [errors.username ? "auth-username-error" : "", isLogin ? "" : "auth-username-hint"].filter(Boolean).join(" ") || undefined
            }
            disabled={pending}
          />
          {!isLogin && (
            <div id="auth-username-hint" className={fieldHint}>
              3–32 letters, numbers, dots, dashes or underscores.
            </div>
          )}
          {errors.username && (
            <div id="auth-username-error" className={fieldError}>
              {errors.username}
            </div>
          )}
        </div>

        <div className={field}>
          <label className={fieldLabel} htmlFor="auth-password">Password</label>
          <PasswordInput
            id="auth-password"
            value={password}
            onChange={(e) => {
              setPassword(e.target.value);
              if (errors.password) setErrors((prev) => ({ ...prev, password: undefined }));
            }}
            autoComplete={isLogin ? "current-password" : "new-password"}
            visible={showPassword}
            onToggleVisible={() => setShowPassword(!showPassword)}
            invalid={!!errors.password}
            describedBy={
              [errors.password ? "auth-password-error" : "", isLogin ? "" : "auth-password-hint"].filter(Boolean).join(" ") || undefined
            }
            disabled={pending}
          />
          {!isLogin && (
            <div id="auth-password-hint" className={fieldHint}>
              At least 8 characters.
            </div>
          )}
          {errors.password && (
            <div id="auth-password-error" className={fieldError}>
              {errors.password}
            </div>
          )}
        </div>

        {!isLogin && (
          <div className={field}>
            <label className={fieldLabel} htmlFor="auth-confirm">Confirm password</label>
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
              <div id="auth-confirm-error" className={fieldError}>
                {errors.confirmPassword}
              </div>
            )}
          </div>
        )}

        <button type="submit" className={`${btn.primary} ${submitFull} mt-2`} disabled={pending}>
          {pending ? <span className={spinnerOnFill} aria-hidden="true" /> : null}
          {isLogin ? (pending ? "Logging in…" : "Login") : pending ? "Creating account…" : "Create account"}
        </button>
      </form>

      <p className="mt-6 mb-0 text-center text-[0.9rem] text-ink-muted">
        {isLogin ? "Don't have an account?" : "Already have an account?"}{" "}
        <button
          type="button"
          className={textLink}
          onClick={() => {
            setMode(isLogin ? "register" : "login");
            setErrors({});
            setUsername("");
            setPassword("");
            setConfirmPassword("");
          }}
          disabled={pending}
        >
          {isLogin ? "Create one" : "Login"}
        </button>
      </p>
    </div>
  );
}
