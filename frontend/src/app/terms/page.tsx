import type { Metadata } from "next";
import Link from "next/link";
import { ContactLine, LegalPage } from "@/components/legal/legal-page";

export const metadata: Metadata = {
  title: "Terms of Use",
  description: "The rules for using Oratio, what its scores mean, and what it is not.",
};

export default function TermsPage() {
  return (
    <LegalPage
      eyebrow="Terms"
      title="Terms of Use"
      intro={
        <p>
          These terms are the agreement between you and Oratio when you use this
          website. By creating an account you accept them, together with the{" "}
          <Link href="/privacy" className="underline underline-offset-4">Privacy Policy</Link>.
          If you do not agree, please do not use the service.
        </p>
      }
      sections={[
        {
          id: "not-official",
          title: "Oratio is not IELTS",
          body: (
            <>
              <p>
                <strong>IELTS</strong> is a registered trademark of the British Council,
                IDP: IELTS Australia and Cambridge University Press &amp; Assessment.
                Oratio is an independent practice service. It is not affiliated with,
                approved by or endorsed by any of them, and it is not a test centre.
              </p>
              <p>
                “Cambridge IELTS” book titles are mentioned only to describe the material
                a practice test follows. They belong to Cambridge University Press &amp;
                Assessment.
              </p>
            </>
          ),
        },
        {
          id: "scores",
          title: "What the scores mean",
          body: (
            <>
              <p>
                Practice material and marking are produced by automated software,
                including large language models. A band from Oratio is an
                <strong> estimate for practice</strong>, measured against the public band
                descriptors. It is not an official result, it cannot be used as proof of
                English ability, and it may differ from the band you receive in the real
                test.
              </p>
              <p>
                We do not promise any band, admission, scholarship or visa outcome.
                Always check the score requirements with your university or the relevant
                immigration authority.
              </p>
            </>
          ),
        },
        {
          id: "account",
          title: "Your account",
          body: (
            <ul>
              <li>You must be 18 or older, or have a parent or guardian&apos;s permission.</li>
              <li>Give a real email address you can read. One account per person.</li>
              <li>Keep your password secret. You are responsible for what happens in your account.</li>
              <li>Tell us straight away if you think someone else has used it.</li>
            </ul>
          ),
        },
        {
          id: "use",
          title: "Fair use",
          body: (
            <>
              <p>You agree not to:</p>
              <ul>
                <li>try to break into, overload, probe or bypass the security of the service or its providers;</li>
                <li>copy, scrape or resell the practice material, or run automated scripts against it;</li>
                <li>use another person&apos;s account, or submit someone else&apos;s personal data;</li>
                <li>upload anything unlawful, abusive, or that you do not have the right to share;</li>
                <li>use the service to cheat in a real examination.</li>
              </ul>
              <p>
                To keep the service working for everyone, we limit how many requests one
                person can make in a short time.
              </p>
            </>
          ),
        },
        {
          id: "content",
          title: "Your work and ours",
          body: (
            <>
              <p>
                Your essays, answers and recordings stay yours. You give us permission to
                store and process them only to mark them, show your progress and run the
                service, as the Privacy Policy describes.
              </p>
              <p>
                The website, its design and the practice material we generate belong to
                Oratio. You may use them for your own preparation, not for commercial
                purposes.
              </p>
            </>
          ),
        },
        {
          id: "pilot",
          title: "A free pilot, provided as it is",
          body: (
            <p>
              Oratio is free and in its pilot stage. Features may change, pause or stop,
              and the service may sometimes be unavailable or make mistakes. It is
              provided “as is”, without warranties of any kind, to the extent the law
              allows.
            </p>
          ),
        },
        {
          id: "liability",
          title: "Limits of our responsibility",
          body: (
            <p>
              As far as the law allows, Oratio is not liable for indirect or consequential
              loss, including a test result, a missed deadline or a refused application,
              arising from use of the service. Nothing in these terms limits liability that
              cannot be limited by law.
            </p>
          ),
        },
        {
          id: "ending",
          title: "Ending your use",
          body: (
            <p>
              You can stop at any time and delete your account in Settings. We may
              suspend or close an account that breaks these terms or puts the service or
              other users at risk.
            </p>
          ),
        },
        {
          id: "law",
          title: "Law and changes",
          body: (
            <>
              <p>
                These terms are governed by the laws of Bangladesh, and the courts of
                Bangladesh have jurisdiction. If you live elsewhere, you keep any protections
                your local consumer law gives you.
              </p>
              <p>
                We may update these terms. If a change matters, we will update the date
                above and ask you to accept again. Questions: <ContactLine />.
              </p>
            </>
          ),
        },
      ]}
    />
  );
}
