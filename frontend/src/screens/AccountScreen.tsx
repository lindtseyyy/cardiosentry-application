import React, { useState } from "react";
import { api, isApiError, friendlyMessage } from "../api/client";
import PasswordInput from "../components/PasswordInput";
import { btn, field, fieldError, fieldHint, fieldLabel, msg, pageSub, pageTitle, spinnerOnFill } from "../ui";

// Settings cards share the auth card surface; the column is wider for sectioned content.
const settingsCard = "bg-panel border border-line rounded-card p-6 shadow-card max-compact:p-5 flex flex-col gap-4";
const sectionHeading = "m-0 text-[1rem] font-semibold text-ink";
const sectionNote = "mt-0.5 mb-0 text-[0.85rem] text-ink-muted";
// Card submit: full width on phones, content width from `compact` up.
const cardSubmit = "w-full min-h-11 px-5 text-[0.95rem] font-semibold rounded-control compact:w-auto compact:self-start";

const USERNAME_RE = /^[A-Za-z0-9_.-]{3,32}$/;

type FieldErrors = Partial<Record<"username" | "currentPassword" | "newPassword" | "confirmPassword" | "form", string>>;

/** Route an update error to the field it belongs to. */
function errorsFrom(err: unknown): FieldErrors {
  if (!isApiError(err)) return { form: "An unexpected error occurred." };
  const text = friendlyMessage(err.code, err.message);
  switch (err.code) {
    case "INVALID_USERNAME":
    case "USERNAME_TAKEN":
      return { username: text };
    case "INVALID_PASSWORD":
      return { newPassword: text };
    case "WRONG_PASSWORD":
      return { currentPassword: text };
    default:
      return { form: text };
  }
}

function FieldError({ id, text }: { id: string; text?: string }) {
  return text ? (
    <div id={id} className={fieldError}>
      {text}
    </div>
  ) : null;
}

interface AccountScreenProps {
  username: string;
  onUpdated: (username: string) => void;
  onSignOut?: () => void;
}

export default function AccountScreen({ username: currentUsername, onUpdated, onSignOut }: AccountScreenProps) {
  return (
    <div className="w-full my-10 max-compact:my-6">
      <h1 className={pageTitle}>Settings</h1>
      <p className={pageSub}>
        Logged in as <span className="font-medium text-ink">{currentUsername}</span>
      </p>

      <div className="flex flex-col gap-4 mt-6">
        <UsernameForm currentUsername={currentUsername} onUpdated={onUpdated} />
        <PasswordForm />

        {onSignOut ? (
          <section
            className="bg-panel border border-line rounded-card p-6 shadow-card max-compact:p-5 flex items-center justify-between gap-4 max-tiny:flex-col max-tiny:items-stretch"
            aria-labelledby="settings-session"
          >
            <div>
              <h2 id="settings-session" className={sectionHeading}>Session</h2>
              <p className={sectionNote}>Log out of CardioSentry on this device.</p>
            </div>
            <button
              type="button"
              className="flex-none min-h-10 px-4 rounded-control bg-panel border-error-line text-matte-red text-[0.9rem] font-semibold hover:bg-error-wash hover:border-matte-red"
              onClick={onSignOut}
            >
              Log out
            </button>
          </section>
        ) : null}
      </div>
    </div>
  );
}

function UsernameForm({
  currentUsername,
  onUpdated,
}: {
  currentUsername: string;
  onUpdated: (username: string) => void;
}) {
  const [username, setUsername] = useState(currentUsername);
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [pending, setPending] = useState(false);
  const [errors, setErrors] = useState<FieldErrors>({});
  const [success, setSuccess] = useState("");

  const changed = username.trim().toLowerCase() !== currentUsername.toLowerCase();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSuccess("");
    const next: FieldErrors = {};
    if (!USERNAME_RE.test(username.trim())) next.username = "Use 3–32 letters, numbers, dots, dashes or underscores.";
    if (!password) next.currentPassword = "Enter your current password to confirm.";
    setErrors(next);
    if (Object.keys(next).length > 0) return;

    setPending(true);
    try {
      const resp = await api.updateAccount({ current_password: password, username: username.trim() });
      onUpdated(resp.username);
      setUsername(resp.username);
      setPassword("");
      setSuccess(`Username changed to ${resp.username}.`);
    } catch (err: unknown) {
      setErrors(errorsFrom(err));
    } finally {
      setPending(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className={settingsCard} aria-labelledby="settings-username" noValidate>
      <div>
        <h2 id="settings-username" className={sectionHeading}>Username</h2>
        <p className={sectionNote}>The name you use to log in.</p>
      </div>

      {errors.form && <div className={msg.error} role="alert">{errors.form}</div>}
      {success && <div className={msg.info} aria-live="polite">{success}</div>}

      <div className={field}>
        <label className={fieldLabel} htmlFor="account-username">New username</label>
        <input
          id="account-username"
          type="text"
          value={username}
          onChange={(e) => {
            setUsername(e.target.value);
            setSuccess("");
            if (errors.username) setErrors((prev) => ({ ...prev, username: undefined }));
          }}
          autoComplete="username"
          autoCapitalize="none"
          autoCorrect="off"
          spellCheck={false}
          aria-invalid={!!errors.username}
          aria-describedby={errors.username ? "account-username-error" : undefined}
          disabled={pending}
        />
        <FieldError id="account-username-error" text={errors.username} />
      </div>

      {changed && (
        <div className={field}>
          <label className={fieldLabel} htmlFor="account-username-password">Current password</label>
          <PasswordInput
            id="account-username-password"
            value={password}
            onChange={(e) => {
              setPassword(e.target.value);
              if (errors.currentPassword) setErrors((prev) => ({ ...prev, currentPassword: undefined }));
            }}
            autoComplete="current-password"
            visible={showPassword}
            onToggleVisible={() => setShowPassword(!showPassword)}
            invalid={!!errors.currentPassword}
            describedBy={errors.currentPassword ? "account-username-password-error" : "account-username-password-hint"}
            disabled={pending}
          />
          {errors.currentPassword ? (
            <FieldError id="account-username-password-error" text={errors.currentPassword} />
          ) : (
            <div id="account-username-password-hint" className={fieldHint}>
              Required to confirm the change.
            </div>
          )}
        </div>
      )}

      <button type="submit" className={`${btn.primary} ${cardSubmit}`} disabled={pending || !changed}>
        {pending ? <span className={spinnerOnFill} aria-hidden="true" /> : null}
        {pending ? "Saving…" : "Save username"}
      </button>
    </form>
  );
}

function PasswordForm() {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showCurrent, setShowCurrent] = useState(false);
  const [showNew, setShowNew] = useState(false);
  const [pending, setPending] = useState(false);
  const [errors, setErrors] = useState<FieldErrors>({});
  const [success, setSuccess] = useState("");

  const clear = (key: keyof FieldErrors) => {
    setSuccess("");
    if (errors[key]) setErrors((prev) => ({ ...prev, [key]: undefined }));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSuccess("");
    const next: FieldErrors = {};
    if (!currentPassword) next.currentPassword = "Enter your current password.";
    if (newPassword.length < 8 || newPassword.length > 128) next.newPassword = "Use 8–128 characters.";
    if (!next.newPassword && confirmPassword !== newPassword) next.confirmPassword = "Passwords do not match.";
    setErrors(next);
    if (Object.keys(next).length > 0) return;

    setPending(true);
    try {
      await api.updateAccount({ current_password: currentPassword, new_password: newPassword });
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      setSuccess("Password changed. Other devices were logged out.");
    } catch (err: unknown) {
      setErrors(errorsFrom(err));
    } finally {
      setPending(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className={settingsCard} aria-labelledby="settings-password" noValidate>
      <div>
        <h2 id="settings-password" className={sectionHeading}>Change password</h2>
        <p className={sectionNote}>You'll stay logged in here. Other devices will need to log in again.</p>
      </div>

      {errors.form && <div className={msg.error} role="alert">{errors.form}</div>}
      {success && <div className={msg.info} aria-live="polite">{success}</div>}

      <div className={field}>
        <label className={fieldLabel} htmlFor="account-current-password">Current password</label>
        <PasswordInput
          id="account-current-password"
          value={currentPassword}
          onChange={(e) => {
            setCurrentPassword(e.target.value);
            clear("currentPassword");
          }}
          autoComplete="current-password"
          visible={showCurrent}
          onToggleVisible={() => setShowCurrent(!showCurrent)}
          invalid={!!errors.currentPassword}
          describedBy={errors.currentPassword ? "account-current-password-error" : undefined}
          disabled={pending}
        />
        <FieldError id="account-current-password-error" text={errors.currentPassword} />
      </div>

      <div className={field}>
        <label className={fieldLabel} htmlFor="account-new-password">New password</label>
        <PasswordInput
          id="account-new-password"
          value={newPassword}
          onChange={(e) => {
            setNewPassword(e.target.value);
            clear("newPassword");
          }}
          autoComplete="new-password"
          visible={showNew}
          onToggleVisible={() => setShowNew(!showNew)}
          invalid={!!errors.newPassword}
          describedBy={errors.newPassword ? "account-new-password-error" : "account-new-password-hint"}
          disabled={pending}
        />
        {errors.newPassword ? (
          <FieldError id="account-new-password-error" text={errors.newPassword} />
        ) : (
          <div id="account-new-password-hint" className={fieldHint}>
            At least 8 characters.
          </div>
        )}
      </div>

      <div className={field}>
        <label className={fieldLabel} htmlFor="account-confirm">Confirm new password</label>
        <PasswordInput
          id="account-confirm"
          value={confirmPassword}
          onChange={(e) => {
            setConfirmPassword(e.target.value);
            clear("confirmPassword");
          }}
          autoComplete="new-password"
          visible={showNew}
          invalid={!!errors.confirmPassword}
          describedBy={errors.confirmPassword ? "account-confirm-error" : undefined}
          disabled={pending}
        />
        <FieldError id="account-confirm-error" text={errors.confirmPassword} />
      </div>

      <button type="submit" className={`${btn.primary} ${cardSubmit}`} disabled={pending}>
        {pending ? <span className={spinnerOnFill} aria-hidden="true" /> : null}
        {pending ? "Changing…" : "Change password"}
      </button>
    </form>
  );
}
