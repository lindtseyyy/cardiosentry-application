import { useApp } from "../AppContext";
import PrivacyNotice from "../components/PrivacyNotice";
import { panel, sectionTitle } from "../ui";

export default function PrivacyScreen({ onBack }: { onBack: () => void }) {
  const { config } = useApp();
  return (
    <div>
      <h1 className={`${sectionTitle} mt-0 mb-4.5 print:hidden`}>Data Privacy Notice</h1>
      <div className={`${panel} mb-4.5`}>
        <PrivacyNotice privacy={config?.privacy ?? null} />
      </div>
      <div className="flex gap-2.5 flex-wrap mt-6 pt-4 border-t border-line">
        <button type="button" onClick={onBack}>
          Back to Classify ECG
        </button>
      </div>
    </div>
  );
}
