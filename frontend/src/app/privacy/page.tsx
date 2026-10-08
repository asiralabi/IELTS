import type { Metadata } from "next";
import Link from "next/link";
import { ContactLine, LegalPage } from "@/components/legal/legal-page";

export const metadata: Metadata = {
  title: "Privacy Policy",
  description: "What Oratio collects, why, who processes it, and how to see or delete it.",
};

export default function PrivacyPage() {
  return (
    <LegalPage
      eyebrow="Privacy"
      title="Privacy Policy"
      intro={
        <>
          <p>
            Oratio is an IELTS practice service. To mark your work we have to read it,
            so this page sets out plainly what we collect, why, who else handles it,
            how long we keep it, and how you can see or delete it.
          </p>
          <p>
            We wrote it to meet Bangladesh&apos;s Personal Data Protection Ordinance
            2025. Where you use Oratio from the European Union or the United Kingdom,
            the rights under the GDPR and UK GDPR apply to you as well.
          </p>
        </>
      }
      sections={[
        {
          id: "collect",
          title: "What we collect",
          body: (
            <ul>
              <li><strong>Account details:</strong> your email address, your name if you give it, your target band, and your password, which is stored only as a one-way hash.</li>
              <li><strong>Your practice work:</strong> essays, speaking transcripts, any speaking audio you upload, your answers to reading and listening questions, mock exams, and the scores and feedback we produce.</li>
              <li><strong>Chats:</strong> questions you ask in “Ask Oratio” and the replies.</li>
              <li><strong>Feedback:</strong> notes you send through the feedback form, with the email you give, the page you were on and your browser type.</li>
              <li><strong>Technical data:</strong> your IP address, which our hosting provider logs and our servers use briefly to limit abuse. We do not use analytics or advertising trackers.</li>
              <li><strong>Consent record:</strong> the date you accepted these terms and which version you accepted.</li>
            </ul>
          ),
        },
        {
          id: "why",
          title: "Why we use it",
          body: (
            <>
              <p>We use your data only to run the service you asked for:</p>
              <ul>
                <li>to create and secure your account;</li>
                <li>to generate practice material and mark your answers;</li>
                <li>to show your progress and build your study plan;</li>
                <li>to answer feedback and fix problems;</li>
                <li>to protect the service from abuse, such as password guessing.</li>
              </ul>
              <p>
                We rely on your <strong>explicit consent</strong>, given when you create
                an account. We do not sell your data, and we do not use it for advertising.
              </p>
            </>
          ),
        },
        {
          id: "automated",
          title: "Automated marking",
          body: (
            <p>
              Questions, recordings and marking are produced by automated software,
              including large language models. No human examiner reviews your work
              unless you write to us about it. Scores are practice estimates against the
              public IELTS band descriptors; they are not official IELTS results and are
              never shared with any test centre, university or embassy.
            </p>
          ),
        },
        {
          id: "processors",
          title: "Who else handles your data",
          body: (
            <>
              <p>A few service providers process data for us, under their own security and privacy terms:</p>
              <ul>
                <li><strong>Vercel Inc.</strong> (United States): hosts the website and the application servers.</li>
                <li><strong>Supabase Inc.</strong> (United States): hosts the database that stores your account and practice history.</li>
                <li><strong>NVIDIA Corporation</strong> (United States): runs the language model that receives the text of your essays, transcripts and chat questions so they can be marked or answered.</li>
                <li><strong>Your browser vendor:</strong> if you speak your answer, your browser&apos;s built-in speech recognition turns it into text. In Google Chrome that audio is processed by Google.</li>
              </ul>
              <p>
                This means your data leaves Bangladesh. You agree to these transfers when
                you create an account. We send each provider only what it needs, over
                encrypted connections.
              </p>
            </>
          ),
        },
        {
          id: "keep",
          title: "How long we keep it",
          body: (
            <ul>
              <li>Account data and practice history: for as long as your account exists.</li>
              <li>When you delete your account, everything linked to it is removed from our live database straight away. Copies may remain in our providers&apos; backups for a short period before they are overwritten.</li>
              <li>Feedback sent without an account: up to 12 months.</li>
            </ul>
          ),
        },
        {
          id: "rights",
          title: "Your rights",
          body: (
            <>
              <p>You can:</p>
              <ul>
                <li><strong>See your data.</strong> Settings → “Download my data” gives you a copy of everything linked to your account.</li>
                <li><strong>Delete your data.</strong> Settings → “Delete my account” erases your account and its history at once.</li>
                <li><strong>Correct your data.</strong> Write to us and we will fix anything that is wrong.</li>
                <li><strong>Withdraw consent</strong> at any time by deleting your account. We stop processing straight away.</li>
                <li><strong>Complain</strong> to the data protection authority set up under the Personal Data Protection Ordinance 2025, or to your local authority if you are in the EU or UK.</li>
              </ul>
              <p>For anything else, contact us through <ContactLine />.</p>
            </>
          ),
        },
        {
          id: "children",
          title: "Children",
          body: (
            <p>
              Oratio is meant for people preparing for IELTS, usually aged 16 and over.
              If you are under 18, you need a parent or guardian&apos;s permission to
              create an account. We do not profile young users or show them advertising.
              If a parent believes their child has signed up without permission, contact
              us and we will delete the account.
            </p>
          ),
        },
        {
          id: "security",
          title: "Security",
          body: (
            <p>
              Passwords are hashed with bcrypt. All traffic is encrypted. Every request
              that reads your work is checked against your account, sign-in attempts are
              rate-limited, and only the Oratio team can change the shared reference
              material. No system is perfectly secure. If a breach puts your data at
              risk, we will tell you and the authorities as the law requires.
            </p>
          ),
        },
        {
          id: "storage",
          title: "Storage in your browser",
          body: (
            <p>
              We use your browser&apos;s local storage, not cookies, to keep you signed in,
              remember your light or dark theme, and save your flashcard progress. These
              are needed for the service to work, and they never leave your device except
              to sign you in.
            </p>
          ),
        },
        {
          id: "changes",
          title: "Changes to this policy",
          body: (
            <p>
              If we change this policy in a way that matters, we will update the date
              above and ask for your consent again before relying on the new terms. The{" "}
              <Link href="/terms" className="underline underline-offset-4">Terms of Use</Link>{" "}
              explain the rest of the rules of the service.
            </p>
          ),
        },
      ]}
    />
  );
}
