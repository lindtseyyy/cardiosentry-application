import type { PrivacyConfig } from "../api/types";

// The Data Privacy Notice under the Philippine Data Privacy Act of 2012
// (Republic Act No. 10173), its IRR, and National Privacy Commission (NPC)
// issuances. Every factual claim here describes what the app actually does —
// change the backend (GPS stripping, trash-not-unlink, no outbound traffic,
// guidance answers not saved, accounts, account ids / session revocation,
// records in a local PostgreSQL database) and this
// text must change with it, along with
// PRIVACY_NOTICE_VERSION in backend/api/config.py.

const NOT_SET = "Not yet configured — ask the person operating this device.";

/** One-paragraph version shown before the first upload. */
export function PrivacySummary() {
  return (
    <p className="privacy-summary">
      A photograph of an ECG is <strong>health information</strong> — sensitive
      personal information under the Philippine Data Privacy Act of 2012 (RA
      10173). CardioSentry stores the photograph, the processed images and the
      model's scores on this computer only, for research on how the model
      performs on real photographs. It is not a diagnosis. Cover the patient's
      name and ID before photographing if you can.
    </p>
  );
}

export default function PrivacyNotice({ privacy }: { privacy: PrivacyConfig | null }) {
  return (
    <article className="privacy-notice">
      <p className="privacy-meta">
        Version {privacy?.notice_version ?? "—"} · Issued under the Data Privacy Act
        of 2012 (Republic Act No. 10173)
      </p>

      <h2>1. Who is responsible for your data</h2>
      <p>
        The personal information controller for data collected through this
        installation of CardioSentry is:
      </p>
      <dl className="privacy-contact">
        <dt>Controller</dt>
        <dd>{privacy?.controller || NOT_SET}</dd>
        <dt>Contact / Data Protection Officer</dt>
        <dd>{privacy?.contact || NOT_SET}</dd>
      </dl>

      <h2>2. What we collect</h2>
      <ul>
        <li>
          <strong>The photograph of the ECG sheet</strong> you take or choose. The ECG
          tracing is health information, which RA 10173 (Sec. 3(l)) classifies as
          sensitive personal information. A printed sheet may also show the
          patient's name, ID number, age and sex.
        </li>
        <li>
          <strong>Images derived from it:</strong> a cropped and straightened copy of
          the sheet, the exact image given to the model, and — if requested — heat
          maps showing where the model looked.
        </li>
        <li>
          <strong>Model results:</strong> the score for each finding, the thresholds
          used, and timing and version details.
        </li>
        <li>
          <strong>Photo and device details:</strong> camera make and model, exposure
          settings, image size and orientation from the photo's metadata, the
          file name, and your browser's user-agent string.{" "}
          <strong>GPS location is removed</strong> from the stored photograph.
        </li>
        <li>
          <strong>Anything you type</strong> into optional fields, such as a sheet code,
          notes or reference labels.
        </li>
        <li>
          <strong>Account details:</strong> your username, a salted one-way hash of
          your password (never the password itself), and a sign-in session record,
          kept in this computer's local database. Your account keeps a permanent account ID —
          the username first registered — that does not change when you change
          your username. Each capture records the account ID of the account that
          created it.
        </li>
      </ul>
      <p>
        The age group, symptoms and history you may enter to refine urgency
        guidance are used only to compute that guidance and are{" "}
        <strong>not saved</strong>.
      </p>

      <h2>3. Why we collect it</h2>
      <p>
        Solely for research: to measure how the CardioSentry model behaves on
        real photographs of printed ECGs, and to keep a complete, reproducible
        record of each analysis. Results are experimental scores from an
        uncalibrated model. They are <strong>not a medical diagnosis</strong>, and no
        decision about anyone's care is made by this app alone — a qualified
        health professional must interpret every ECG. The data is not sold,
        used for marketing, or used to profile anyone.
      </p>

      <h2>4. Legal basis</h2>
      <p>
        We process this sensitive personal information on the basis of the{" "}
        <strong>consent</strong> of the data subject (RA 10173, Sec. 13(a)), given before
        each photograph is uploaded. For a patient under 18, consent must come
        from a parent or legal guardian. You may withdraw consent at any time
        (see section 7); withdrawal does not affect processing already done.
      </p>

      <h2>5. Where it is kept and who can see it</h2>
      <ul>
        <li>
          Photographs and the images derived from them are stored as files, and
          the records (account details, capture details, scores, heat-map details
          and anything you type) in a PostgreSQL database, both on the computer
          running CardioSentry. The app connects to that database only on the same
          computer and does not send your photographs or results to any cloud
          service or third party.
        </li>
        <li>
          Your phone talks to that computer over the local network only. The app
          is not exposed to the internet, and access can be restricted to a
          shared access token.
        </li>
        <li>
          In the app, each scan is visible only to the account that created it.
          Scans made before accounts existed belong to the administrator account.
        </li>
        <li>
          Only the controller and research personnel bound by confidentiality can
          access the stored data. Any research output — reports, the thesis,
          publications — uses aggregate or de-identified results, never a
          photograph showing a patient's identity.
        </li>
        <li>
          If any copy is ever moved off that computer (for example, to backup or
          cloud storage, including outside the Philippines), it will be only
          with your consent and with safeguards equivalent to RA 10173.
        </li>
      </ul>

      <h2>6. How long it is kept</h2>
      <p>
        Data is kept only for as long as the research study needs it, and is
        then permanently deleted. Deleting a capture in the app moves its images
        to a holding folder and marks its record deleted in the database, so
        mistakes can be undone; ask the controller to erase it permanently.
      </p>

      <h2>7. Your rights as a data subject</h2>
      <p>Under RA 10173 (Secs. 16–18) you have the right to:</p>
      <ul>
        <li>be informed of how your data is processed (this notice);</li>
        <li>access the data held about you and obtain a copy;</li>
        <li>object to processing, and withdraw your consent;</li>
        <li>have inaccurate data corrected;</li>
        <li>have your data blocked, removed or destroyed;</li>
        <li>receive your data in a commonly used electronic format (portability);</li>
        <li>be indemnified for damages from inaccurate, unlawfully obtained or
          unauthorized use of your data;</li>
        <li>
          file a complaint with the <strong>National Privacy Commission</strong>{" "}
          (privacy.gov.ph).
        </li>
      </ul>
      <p>
        To exercise any of these rights, contact the controller in section 1.
        Give the date and time the photograph was taken so the record can be
        found.
      </p>

      <h2>8. Security and breaches</h2>
      <p>
        We apply organizational, physical and technical measures (RA 10173,
        Sec. 20): local-only storage, location stripping, password-protected
        accounts, restricted access to the computer and its data folder, and no
        publication of identifiable images. Changing your password signs out the
        account's other devices. If a personal data breach occurs that is likely
        to harm you, the
        controller will notify the National Privacy Commission and the affected
        data subjects within 72 hours of knowing about it, as NPC Circular
        16-03 requires.
      </p>

      <h2>9. Before you photograph a sheet</h2>
      <ul>
        <li>Only photograph an ECG with the patient's (or guardian's) consent.</li>
        <li>
          Fold over or cover the printed name, ID number and other identifiers
          if you can — the model does not need them.
        </li>
      </ul>

      <h2>10. Changes to this notice</h2>
      <p>
        If this notice changes materially, the app will ask you to read and
        accept the new version before the next upload. The version you accepted
        is recorded with each capture.
      </p>
    </article>
  );
}
