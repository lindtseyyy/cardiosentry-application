import { useApp } from "../AppContext";
import PrivacyNotice from "../components/PrivacyNotice";

export default function PrivacyScreen({ onBack }: { onBack: () => void }) {
  const { config } = useApp();
  return (
    <div>
      <h1 className="section-title page-heading">Data Privacy Notice</h1>
      <div className="panel">
        <PrivacyNotice privacy={config?.privacy ?? null} />
      </div>
      <div className="footer-nav">
        <button type="button" onClick={onBack}>
          Back to New ECG
        </button>
      </div>
    </div>
  );
}
