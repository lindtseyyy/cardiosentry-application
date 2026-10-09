import React, { useState } from "react";
import { api, isApiError, friendlyMessage } from "../api/client";
import PasswordInput from "../components/PasswordInput";

interface AccountScreenProps {
  username: string;
  onUpdated: (username: string) => void;
  onSignOut?: () => void;
}

export default function AccountScreen({
  username: initialUsername,
  onUpdated,
  onSignOut,
}: AccountScreenProps) {
  const [username, setUsername] = useState(initialUsername);
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [currentPassword, setCurrentPassword] = useState("");

  const [showNewPassword, setShowNewPassword] = useState(false);
  const [showCurrentPassword, setShowCurrentPassword] = useState(false);
  const [pending, setPending] = useState(false);

  const [errors, setErrors] = useState<{
    username?: string;
    newPassword?: string;
    confirmPassword?: string;
    currentPassword?: string;
    form?: string;
  }>({});
  const [successMsg, setSuccessMsg] = useState("");

  const validateAll = (): boolean => {
    let isValid = true;
    const next: typeof errors = {};

    const u = username.trim();
    if (!/^[A-Za-z0-9_.-]{3,32}$/.test(u)) {
      next.username = "Username must be 3-32 characters (letters, numbers, _, ., -).";
      isValid = false;
    }

    if (newPassword && (newPassword.length < 8 || newPassword.length > 128)) {
      next.newPassword = "Password must be 8-128 characters.";
      isValid = false;
    }

    if (newPassword && confirmPassword !== newPassword) {
      next.confirmPassword = "Passwords do not match.";
      isValid = false;
    }

    if (!currentPassword) {
      next.currentPassword = "Current password is required to make changes.";
      isValid = false;
    }

    setErrors(next);
    return isValid;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSuccessMsg("");
    setErrors({});
    
    if (username.trim().toLowerCase() === initialUsername.toLowerCase() && !newPassword) {
      setErrors({ form: "Nothing to change." });
      return;
    }

    if (!validateAll()) return;

    setPending(true);

    try {
      const resp = await api.updateAccount({
        current_password: currentPassword,
        username: username.trim().toLowerCase() !== initialUsername.toLowerCase() ? username.trim() : undefined,
        new_password: newPassword ? newPassword : undefined,
      });

      onUpdated(resp.username);
      setNewPassword("");
      setConfirmPassword("");
      setCurrentPassword("");
      
      if (newPassword) {
        setSuccessMsg("Account updated. Other devices were signed out.");
      } else {
        setSuccessMsg("Account updated.");
      }
    } catch (err: unknown) {
      if (isApiError(err)) {
        if (err.code === "INVALID_USERNAME" || err.code === "USERNAME_TAKEN") {
          setErrors({ username: friendlyMessage(err.code, err.message) });
        } else if (err.code === "INVALID_PASSWORD") {
          setErrors({ newPassword: friendlyMessage(err.code, err.message) });
        } else if (err.code === "WRONG_PASSWORD") {
          setErrors({ currentPassword: friendlyMessage(err.code, err.message) });
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
      <h2>Settings</h2>
      {errors.form && (
        <div className="msg error" role="alert">
          {errors.form}
        </div>
      )}
      {successMsg && (
        <div className="msg info" aria-live="polite">
          {successMsg}
        </div>
      )}

      <form onSubmit={handleSubmit} className="vstack mt" noValidate>
        <div className="field">
          <label htmlFor="account-username">Username</label>
          <input
            id="account-username"
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
            aria-describedby={errors.username ? "account-username-error" : undefined}
            disabled={pending}
          />
          {errors.username && (
            <div id="account-username-error" className="field-error">
              {errors.username}
            </div>
          )}
        </div>

        <div className="field mt">
          <label htmlFor="account-new-password">New password</label>
          <div className="hint" id="account-new-password-hint">Leave blank to keep your current password</div>
          <PasswordInput
            id="account-new-password"
            value={newPassword}
            onChange={(e) => {
              setNewPassword(e.target.value);
              if (errors.newPassword) setErrors((prev) => ({ ...prev, newPassword: undefined }));
            }}
            autoComplete="new-password"
            visible={showNewPassword}
            onToggleVisible={() => setShowNewPassword(!showNewPassword)}
            invalid={!!errors.newPassword}
            describedBy={errors.newPassword ? "account-new-password-error account-new-password-hint" : "account-new-password-hint"}
            disabled={pending}
          />
          {errors.newPassword && (
            <div id="account-new-password-error" className="field-error">
              {errors.newPassword}
            </div>
          )}
        </div>

        {newPassword && (
          <div className="field mt">
            <label htmlFor="account-confirm">Confirm new password</label>
            <PasswordInput
              id="account-confirm"
              value={confirmPassword}
              onChange={(e) => {
                setConfirmPassword(e.target.value);
                if (errors.confirmPassword) setErrors((prev) => ({ ...prev, confirmPassword: undefined }));
              }}
              autoComplete="new-password"
              visible={showNewPassword}
              invalid={!!errors.confirmPassword}
              describedBy={errors.confirmPassword ? "account-confirm-error" : undefined}
              disabled={pending}
            />
            {errors.confirmPassword && (
              <div id="account-confirm-error" className="field-error">
                {errors.confirmPassword}
              </div>
            )}
          </div>
        )}
        
        <div className="field mt">
          <label htmlFor="account-current-password">Current password</label>
          <PasswordInput
            id="account-current-password"
            value={currentPassword}
            onChange={(e) => {
              setCurrentPassword(e.target.value);
              if (errors.currentPassword) setErrors((prev) => ({ ...prev, currentPassword: undefined }));
            }}
            autoComplete="current-password"
            visible={showCurrentPassword}
            onToggleVisible={() => setShowCurrentPassword(!showCurrentPassword)}
            invalid={!!errors.currentPassword}
            describedBy={errors.currentPassword ? "account-current-password-error" : undefined}
            disabled={pending}
          />
          {errors.currentPassword && (
            <div id="account-current-password-error" className="field-error">
              {errors.currentPassword}
            </div>
          )}
        </div>

        <div className="auth-actions mt-lg">
          <button type="submit" className="primary auth-submit-btn" disabled={pending}>
            Save changes
          </button>
        </div>
      </form>

      {onSignOut ? (
        <div className="account-signout-block">
          <button
            type="button"
            className="danger auth-submit-btn account-signout-btn"
            onClick={onSignOut}
          >
            Sign out
          </button>
        </div>
      ) : null}
    </div>
  );
}
