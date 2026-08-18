
What is path traversal, and how to prevent it? | Web Security Academy
My account
Products
Solutions
Research
Academy
Support
Company
Customers
About
Blog
Careers
Legal
Contact
Resellers
My account
Customers
About
Blog
Careers
Legal
Contact
Resellers
Burp AT
Agentic AI that extends human-led pentesting.
Burp Suite DAST
The enterprise-enabled dynamic web vulnerability scanner.
Burp Suite Professional
The world's #1 web penetration testing toolkit.
Burp Suite Community Edition
The best manual tools to start web security testing.
View all product editions
Burp Scanner
Burp Suite's web vulnerability scanner
Attack surface visibility
Improve security posture, prioritize manual testing, free up time.
CI-driven scanning
More proactive security - find and fix vulnerabilities earlier.
Application security testing
See how our software enables the world to secure the web.
DevSecOps
Catch critical bugs; ship more secure software, more quickly.
Penetration testing
Accelerate penetration testing - find more bugs, more quickly.
Automated scanning
Scale dynamic scanning. Reduce risk. Save time/money.
Bug bounty hunting
Level up your hacking and earn more bug bounties.
Compliance
Enhance security monitoring to comply with confidence.
View all solutions
Product comparison
What's the difference between Pro and DAST?
Support Center
Get help and advice from our experts on all things Burp.
Documentation
Tutorials and guides for Burp Suite.
Get Started - Professional
Get started with Burp Suite Professional.
Get Started - DAST
Get started with Burp Suite DAST.
Downloads
Download the latest version of Burp Suite.
Visit the Support Center
Downloads
Download the latest version of Burp Suite.
Academy home
Dashboard
Learning paths
Latest topics
Request smuggling
Web cache deception
Web LLM attacks
API testing
NoSQL injection
View all topics
All content
All labs
All topics
Mystery labs
Hall of Fame
Leaderboard
Interview - Kamil Vavra
Interview - Johnny Villarreal
Interview - Andres Rauschecker
Get started
Get certified
Get certified
How to prepare
How it works
Practice exam
Exam hints and guidance
What the exam involves
FAQs
Validate your certification
Back to all topics
Path traversal
What is path traversal?
Reading arbitrary files via path traversal
Common obstacles
Preventing
View all path traversal labs
Web Security Academy Path traversal
Path traversal
In this section, we explain:
What path traversal is.
How to carry out path traversal attacks and circumvent common obstacles.
How to prevent path traversal vulnerabilities.
Labs
If you're familiar with the basic concepts behind path traversal and want to practice exploiting them on some realistic, deliberately vulnerable targets, you can access labs in this topic from the link below.
View all path traversal labs What is path traversal?
Path traversal is also known as directory traversal. These vulnerabilities enable an attacker to read arbitrary files on the server that is running an application. This might include:
Application code and data.
Credentials for back-end systems.
Sensitive operating system files.
In some cases, an attacker might be able to write to arbitrary files on the server, allowing them to modify application data or behavior, and ultimately take full control of the server.
Reading arbitrary files via path traversal
Imagine a shopping application that displays images of items for sale. This might load an image using the following HTML:
&lt;img src="/loadImage?filename=218.png"&gt;
The loadImage URL takes a filename parameter and returns the contents of the specified file. The image files are stored on disk in the location /var/www/images/ . To return an image, the application appends the requested filename to this base directory and uses a filesystem API to read the contents of the file. In other words, the application reads from the following file path:
/var/www/images/218.png
This application implements no defenses against path traversal attacks. As a result, an attacker can request the following URL to retrieve the /etc/passwd file from the server's filesystem:
https://insecure-website.com/loadImage?filename=../../../etc/passwd
This causes the application to read from the following file path:
/var/www/images/../../../etc/passwd
The sequence ../ is valid within a file path, and means to step up one level in the directory structure. The three consecutive ../ sequences step up from /var/www/images/ to the filesystem root, and so the file that is actually read is:
/etc/passwd
On Unix-based operating systems, this is a standard file containing details of the users that are registered on the server, but an attacker could retrieve other arbitrary files using the same technique.
On Windows, both ../ and ..\ are valid directory traversal sequences. The following is an example of an equivalent attack against a Windows-based server:
https://insecure-website.com/loadImage?filename=..\..\..\windows\win.ini
Common obstacles to exploiting path traversal vulnerabilities Many applications that place user input into file paths implement defenses against path traversal attacks. These can often be bypassed. If an application strips or blocks directory traversal sequences from the user-supplied filename, it might be possible to bypass the defense using a variety of techniques. You might be able to use an absolute path from the filesystem root, such as filename=/etc/passwd , to directly reference a file without using any traversal sequences.
You might be able to use nested traversal sequences, such as ....// or ....\/ . These revert to simple traversal sequences when the inner sequence is stripped.
In some contexts, such as in a URL path or the filename parameter of a multipart/form-data request, web servers may strip any directory traversal sequences before passing your input to the application. You can sometimes bypass this kind of sanitization by URL encoding, or even double URL encoding, the ../ characters. This results in %2e%2e%2f and %252e%252e%252f respectively. Various non-standard encodings, such as ..%c0%af or ..%ef%bc%8f , may also work. For Burp Suite Professional users, Burp Intruder provides the predefined payload list Fuzzing - path traversal . This contains some encoded path traversal sequences that you can try.
An application may require the user-supplied filename to start with the expected base folder, such as /var/www/images . In this case, it might be possible to include the required base folder followed by suitable traversal sequences. For example: filename=/var/www/images/../../../etc/passwd .
An application may require the user-supplied filename to end with an expected file extension, such as .png . In this case, it might be possible to use a null byte to effectively terminate the file path before the required extension. For example: filename=../../../etc/passwd%00.png .
How to prevent a path traversal attack
The most effective way to prevent path traversal vulnerabilities is to avoid passing user-supplied input to filesystem APIs altogether. Many application functions that do this can be rewritten to deliver the same behavior in a safer way.
If you can't avoid passing user-supplied input to filesystem APIs, we recommend using two layers of defense to prevent attacks:
Validate the user input before processing it. Ideally, compare the user input with a whitelist of permitted values. If that isn't possible, verify that the input contains only permitted content, such as alphanumeric characters only.
After validating the supplied input, append the input to the base directory and use a platform filesystem API to canonicalize the path. Verify that the canonicalized path starts with the expected base directory.
Below is an example of some simple Java code to validate the canonical path of a file based on user input:
File file = new File(BASE_DIRECTORY, userInput);
if (file.getCanonicalPath().startsWith(BASE_DIRECTORY)) {
// process file
}
Read more
Find directory traversal vulnerabilities using Burp Suite's web vulnerability scanner
Find path traversal vulnerabilities using Burp Suite
Try for free
Burp Suite
Web vulnerability scanner
Burp Suite Editions
Release Notes
Vulnerabilities
Cross-site scripting (XSS)
SQL injection
Cross-site request forgery
XML external entity injection
Directory traversal
Server-side request forgery
Customers
Organizations
Testers
Developers
Company
About
Careers
Contact
Legal
Privacy Notice
Modern Slavery Statement
Insights
Web Security Academy
Blog
Research
Follow us
© 2026 PortSwigger Ltd.
