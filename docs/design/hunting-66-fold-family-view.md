# Hunting #66 - fault-KB aggregation view (post-fold, post-critic, post-squeeze)

Machine-generated from the catalogue (`tools/hunting/fold_family_view.py` over
`src/polymerhus/attack/hunting/data/fault-kb.yaml`), not hand-maintained.
Regenerate with `python tools/hunting/fold_family_view.py --catalogue
src/polymerhus/attack/hunting/data/fault-kb.yaml --out
docs/design/hunting-66-fold-family-view.md`.

- Catalogue: 170 entries; selection tier (matching loop): 97; folded recipes: 73.
- Selection tier: 84 Base / 6 Variant / 5 Class / 2 Compound (2 splits + 6 keep-standalone orphans among the 8 Variant/Compound).

## 1. Fold families (20 captures, 73 folded recipes)

### CWE-179 Incorrect Behavior Order: Early Validation [Base] - capture; 1 recipes - The product validates input before applying protection mechanisms that modify the input, which could allow an attacker to bypass the validation via dangerous inputs that only aris...
- CWE-647 Use of Non-Canonical URL Paths for Authorization Decisions

### CWE-184 Incomplete List of Disallowed Inputs [Base] - capture; 1 recipes - The product implements a protection mechanism that relies on a list of inputs (or properties of inputs) that are not allowed by policy or otherwise require other action to neutral...
- CWE-692 Incomplete Denylist to Cross-Site Scripting

### CWE-201 Insertion of Sensitive Information Into Sent Data [Base] - capture; 1 recipes - The code transmits data to another actor, but a portion of the data includes sensitive information that should not be accessible to that actor.
- CWE-598 Use of HTTP Request With Sensitive Query String

### CWE-22 Improper Limitation of a Pathname to a Restricted Directory ('Path Traversal') [Base] - capture; 36 recipes - The product uses external input to construct a pathname that is intended to identify a file or directory that is located underneath a restricted parent directory, but the product...
- CWE-23 Relative Path Traversal
- CWE-24 Path Traversal: '../filedir'
- CWE-25 Path Traversal: '/../filedir'
- CWE-26 Path Traversal: '/dir/../filename'
- CWE-27 Path Traversal: 'dir/../../filename'
- CWE-28 Path Traversal: '..\filedir'
- CWE-29 Path Traversal: '\..\filename'
- CWE-30 Path Traversal: '\dir\..\filename'
- CWE-31 Path Traversal: 'dir\..\..\filename'
- CWE-32 Path Traversal: '...' (Triple Dot)
- CWE-33 Path Traversal: '....' (Multiple Dot)
- CWE-34 Path Traversal: '....//'
- CWE-35 Path Traversal: '.../...//'
- CWE-36 Absolute Path Traversal
- CWE-37 Path Traversal: '/absolute/pathname/here'
- CWE-38 Path Traversal: '\absolute\pathname\here'
- CWE-39 Path Traversal: 'C:dirname'
- CWE-40 Path Traversal: '\\UNC\share\name\' (Windows UNC Share)
- CWE-41 Improper Resolution of Path Equivalence
- CWE-42 Path Equivalence: 'filename.' (Trailing Dot)
- CWE-43 Path Equivalence: 'filename....' (Multiple Trailing Dot)
- CWE-44 Path Equivalence: 'file.name' (Internal Dot)
- CWE-45 Path Equivalence: 'file...name' (Multiple Internal Dot)
- CWE-46 Path Equivalence: 'filename ' (Trailing Space)
- CWE-49 Path Equivalence: 'filename/' (Trailing Slash)
- CWE-50 Path Equivalence: '//multiple/leading/slash'
- CWE-51 Path Equivalence: '/multiple//internal/slash'
- CWE-52 Path Equivalence: '/multiple/trailing/slash//'
- CWE-53 Path Equivalence: '\multiple\\internal\backslash'
- CWE-54 Path Equivalence: 'filedir\' (Trailing Backslash)
- CWE-55 Path Equivalence: '/./' (Single Dot Directory)
- CWE-56 Path Equivalence: 'filedir*' (Wildcard)
- CWE-57 Path Equivalence: 'fakedir/../realdir/filename'
- CWE-58 Path Equivalence: Windows 8.3 Filename
- CWE-59 Improper Link Resolution Before File Access ('Link Following')
- CWE-61 Symbolic Link (Symlink) Following

### CWE-266 Incorrect Privilege Assignment [Base] - capture; 2 recipes - A product incorrectly assigns a privilege to a particular actor, creating an unintended sphere of control for that actor.
- CWE-520 Misconfiguration: Use of Impersonation
- CWE-9 Misconfiguration: Weak Access Permissions for Methods

### CWE-290 Authentication Bypass by Spoofing [Base] - capture; 3 recipes - This attack-focused weakness is caused by incorrectly implemented authentication schemes that are subject to spoofing attacks.
- CWE-291 Reliance on IP Address for Authentication
- CWE-293 Using Referer Field for Authentication
- CWE-350 Reliance on Reverse DNS Resolution for a Security-Critical Action

### CWE-346 Origin Validation Error [Class] - capture; 1 recipes - The product does not properly verify that the source of data or communication is valid.
- CWE-1385 Missing Origin Validation in WebSockets

### CWE-521 Weak Password Requirements [Base] - capture; 1 recipes - The product does not require that users should have strong passwords.
- CWE-258 Empty Password in Configuration File

### CWE-538 Insertion of Sensitive Information into Externally-Accessible File or Directory [Base] - capture; 1 recipes - The product places sensitive information into files or directories that are accessible to actors who are allowed to have access to the files, but not to the sensitive information.
- CWE-651 Exposure of Service-Description File Containing Sensitive Information

### CWE-540 Inclusion of Sensitive Information in Source Code [Base] - capture; 3 recipes - Source code on a web server or repository often contains sensitive information and should generally not be accessible to users.
- CWE-531 Inclusion of Sensitive Information in Test Code
- CWE-541 Inclusion of Sensitive Information in an Include File
- CWE-615 Inclusion of Sensitive Information in Source Code Comments

### CWE-552 Files or Directories Accessible to External Parties [Base] - capture; 6 recipes - The product makes files or directories accessible to unauthorized actors, even though they should not be.
- CWE-219 Storage of File with Sensitive Data Under Web Root
- CWE-433 Unparsed Raw Web Content Delivery
- CWE-527 Exposure of Version-Control Repository to an Unauthorized Control Sphere
- CWE-529 Exposure of Access Control List Files to an Unauthorized Control Sphere
- CWE-530 Exposure of Backup File to an Unauthorized Control Sphere
- CWE-553 Command Shell in Externally Accessible Directory

### CWE-639 Authorization Bypass Through User-Controlled Key [Base] - capture; 1 recipes - The system's authorization functionality does not prevent one user from gaining access to another user's data or record by modifying the key value identifying the data.
- CWE-566 Authorization Bypass Through User-Controlled SQL Primary Key

### CWE-73 External Control of File Name or Path [Base] - capture; 1 recipes - The product allows user input to control or influence paths or file names that are used in filesystem operations.
- CWE-641 Improper Restriction of Names for Files and Other Resources

### CWE-79 Improper Neutralization of Input During Web Page Generation ('Cross-site Scripting') [Base] - capture; 8 recipes - The product does not neutralize or incorrectly neutralizes user-controllable input before it is placed in output that is used as a web page that is served to other users.
- CWE-80 Improper Neutralization of Script-Related HTML Tags in a Web Page (Basic XSS)
- CWE-81 Improper Neutralization of Script in an Error Message Web Page
- CWE-82 Improper Neutralization of Script in Attributes of IMG Tags in a Web Page
- CWE-83 Improper Neutralization of Script in Attributes in a Web Page
- CWE-84 Improper Neutralization of Encoded URI Schemes in a Web Page
- CWE-85 Doubled Character XSS Manipulations
- CWE-86 Improper Neutralization of Invalid Characters in Identifiers in Web Pages
- CWE-87 Improper Neutralization of Alternate XSS Syntax

### CWE-829 Inclusion of Functionality from Untrusted Control Sphere [Base] - capture; 2 recipes - The product imports, requires, or includes executable functionality (such as a library) from a source that is outside of the intended control sphere.
- CWE-830 Inclusion of Web Functionality from an Untrusted Source
- CWE-98 Improper Control of Filename for Include/Require Statement ('Remote File Inclusion')

### CWE-89 Improper Neutralization of Special Elements used in an SQL Command ('SQL Injection') [Base] - capture; 1 recipes - The product constructs all or part of an SQL command using externally-influenced input from an upstream component, but it does not neutralize or incorrectly neutralizes special el...
- CWE-564 SQL Injection: Object-Relational Mapping Query

### CWE-915 Improperly Controlled Modification of Dynamically-Determined Object Attributes [Base] - capture; 1 recipes - The product receives input from an upstream component that specifies multiple attributes, properties, or fields that are to be initialized or updated in an object, but it does not...
- CWE-1321 Improperly Controlled Modification of Object Prototype Attributes ('Prototype Pollution')

### CWE-93 Improper Neutralization of CRLF Sequences ('CRLF Injection') [Base] - capture; 1 recipes - The product uses CRLF (carriage return line feeds) as a special element, e.g.
- CWE-113 Improper Neutralization of CRLF Sequences in HTTP Headers ('HTTP Request/Response Splitting')

### CWE-94 Improper Control of Generation of Code ('Code Injection') [Base] - capture; 1 recipes - The product constructs all or part of a code segment using externally-influenced input from an upstream component, but it does not neutralize or incorrectly neutralizes special el...
- CWE-95 Improper Neutralization of Directives in Dynamically Evaluated Code ('Eval Injection')

### CWE-96 Improper Neutralization of Directives in Statically Saved Code ('Static Code Injection') [Base] - capture; 1 recipes - The product receives input from an upstream component, but it does not neutralize or incorrectly neutralizes code syntax before inserting the input into an executable resource, su...
- CWE-97 Improper Neutralization of Server-Side Includes (SSI) Within a Web Page

## 2. SPLIT entries (critic: distinct fault class, own selection entry)

- CWE-1022 Use of Web Link to Untrusted Target with window.opener Access [Variant]
- CWE-827 Improper Control of Document Type Definition [Variant]

## 3. KEEP-STANDALONE orphans (critic: no promotable capture)

- CWE-352 Cross-Site Request Forgery (CSRF) [Compound]
- CWE-384 Session Fixation [Compound]
- CWE-626 Null Byte Interaction Error (Poison Null Byte) [Variant]
- CWE-644 Improper Neutralization of HTTP Headers for Scripting Syntax [Variant]
- CWE-646 Reliance on File Name or Extension of Externally-Supplied File [Variant]
- CWE-650 Trusting HTTP Permission Methods on the Server Side [Variant]

## 4. Selection-tier View-1000 hierarchy (second-order structure)

Squeeze pass note: the 2026-08-17 squeeze (51 omits, 14 generalises, 254 -> 203 entries) removed the recon-trivial, naive, and framework-named faults; fold families now number 20 captures over 73 recipes. The 2026-08-18 operator relevance pass (33 additional omits and 5 `fold_to` taxonomy corrections, 203 -> 170 entries) collapsed the traversal family onto CWE-22 (its absolute, relative, path-equivalence, and link-following siblings all fold there regardless of View-1000 structure) and folded CWE-641 under CWE-73. See docs/design/hunting-66-fault-omit-critique.md.
