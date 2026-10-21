# Terms of Service and Privacy Policy (rough draft)

> **Draft, not legal advice.** Written as a starting point for a lawyer's review. Bracketed items are placeholders. The text a user signs (the `terms` event in [EVENTS.md](EVENTS.md)) is the final reviewed version, identified by its sha256.

Version: [draft-0] · Effective: [date] · Operator: [legal entity name, address] ("we", "us")

---

## Part 1: Terms of Service

### 1. What the service is
[Service name] (the "Service") is a private research ledger. Members of a collection record documents ("evidence"), statements ("claims"), links between them, and contradictions between claims. Every record is signed with the submitter's Nostr key.

### 2. Accepting these terms
You accept these terms by signing them with your Nostr key. Your signature covers the exact text of this version. If you don't agree, don't use the Service. When we publish a new version, you must sign it before you can submit anything else.

### 3. Your key is your account
- You sign in and submit records with a Nostr key. We never hold or ask for your private key.
- You are responsible for everything signed with your key, including by software or AI agents that you run or that use your key.
- We can't recover a lost key or undo something signed with a stolen one. Keep your key secure.

### 4. What you upload

**4.1 Your guarantee.** By submitting any content, you represent and warrant that:
- (a) you own the copyright and all other rights in it, **or** you have permission or a license from the rights holder that covers this use, **or** your use is otherwise lawful (for example, under a copyright exception or fair use that applies to you);
- (b) uploading it doesn't breach any contract, confidentiality duty or law; and
- (c) it doesn't contain personal data about other people unless you have a lawful basis to share it.

**4.2 Your responsibility.** You are solely responsible for what you upload. You agree to indemnify and hold us harmless from claims, losses and costs (including reasonable legal fees) arising from your content or from your breach of these terms.

**4.3 License to us.** You keep whatever rights you have in your content. You grant us a worldwide, non-exclusive, royalty-free license to store, copy, process (including computing search embeddings), back up, and display your content to members of the collection you submitted it to, for as long as the Service holds it. This license is only for running the Service.

**4.4 Other members.** Members of a collection can read and download everything in it, including a full export. Once shared, content can't be recalled from copies that members have already downloaded.

### 5. Records are permanent
The ledger is append-only. You can't edit or delete a record after submitting it; corrections are new records. We may remove content as described in section 7. Think before you submit.

### 6. Collections
- Every collection is private. The person who creates a collection is its sole owner and decides who its members are.
- The owner is responsible for who they admit. We don't police membership, but we may act on reported abuse.

### 7. Removal and takedowns
- We may remove or disable access to content, or stop accepting records from a key, if we believe it infringes someone's rights, breaks the law or these terms, or exposes us or others to harm.
- **Copyright notices:** send them to [copyright agent / email], with the information required by [17 U.S.C. §512(c)(3) / applicable law]. We will respond promptly. Repeat infringers' keys will be blocked.
- When we remove content, we may keep a record that it existed, who signed it, and why it was removed.

### 8. Acceptable use
Don't use the Service to upload unlawful content; violate privacy; harass anyone; distribute malware; attempt unauthorized access; overload the Service; or submit content you know is fabricated while presenting it as genuine.

### 9. Not advice
Content in the Service is contributed by users and AI agents and may be wrong, incomplete or out of date. Records stating that something is supported, rebutted or contradicted are contributors' assertions, not our conclusions. **Nothing in the Service is medical, legal, financial or other professional advice.** Talk to a qualified professional before acting on anything you read here.

### 10. Disclaimers and liability
- The Service is provided "as is" and "as available", without warranties of any kind, to the extent the law allows.
- To the extent the law allows, we aren't liable for indirect, incidental, special, consequential or punitive damages, or for lost data or profits. Our total liability is limited to [the greater of USD 100 or the amount you paid us in the last 12 months].

### 11. Ending use
You can stop using the Service at any time. We may suspend or end your access at any time, for any reason, including a breach of these terms. Sections 4.2, 5, 9, 10 and 12 survive.

### 12. Governing law
These terms are governed by the laws of [jurisdiction]. Disputes go to the courts of [venue]. [Arbitration clause, if wanted.]

### 13. Contact
[email]

---

## Part 2: Privacy Policy

### What we collect
- **Your public key** and the **records you sign**, exactly as signed.
- **Your Nostr profile** (name, about, picture), fetched from public relays (currently relay.damus.io and relay.primal.net) when you sign in, or submitted by you.
- **Your signed acceptance of these terms.**
- **Technical data:** IP addresses, request logs and session tokens, kept for [30] days for security and debugging.

We don't ask for your email, name, payment details or private key. We don't use advertising trackers.

### How we use it
To run the Service: verifying signatures, storing and searching records, showing them to collection members, backing them up, preventing abuse, and complying with the law. We don't sell your data or use it for advertising.

### Who can see it
- **Collection members** see every record in that collection, along with the public key and profile of whoever signed it.
- **Service providers** who host our servers and backups. Backups are encrypted before they leave our servers and are stored on Filecoin, a decentralized storage network.
- **Authorities**, when the law requires it.

### Retention
Records are kept indefinitely, because the ledger is append-only. Encrypted backups on Filecoin can't be deleted; they can only be made unreadable by destroying their encryption key. Technical logs are kept for [30] days.

### Your rights
Depending on where you live, you may have rights to access, correct, delete or export your data, and to object to processing. Every member can already export their collections. Because records are permanent and signed, deletion may mean replacing a record's content with a removal notice rather than erasing every trace of it. Contact [email] to make a request. [EU/UK: name a lawful basis (legitimate interests / contract), a controller, a representative, and the right to complain to a supervisory authority.]

### Children
The Service isn't for anyone under [16].

### Changes
A new version of this policy takes effect when you sign it.
