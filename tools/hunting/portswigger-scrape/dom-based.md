
DOM-based vulnerabilities | Web Security Academy
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
DOM-based vulnerabilities
What is the DOM?
Taint flow
Sources
Reflected
and stored data
Web messages
Example
sinks
DOM-based XSS
Open redirection
Impact
Sinks
Preventing
Cookie manipulation
Impact
Sinks
Preventing
JavaScript injection
Impact
Sinks
Preventing
Document-domain manipulation
Sinks
Preventing
WebSocket-URL poisoning
Impact
Sinks
Preventing
Link manipulation
Impact
Sinks
Preventing
Web message manipulation
Sinks
Preventing
Ajax request-header manipulation
Impact
Sinks
Preventing
Local file-path manipulation
Impact
Sinks
Preventing
Client-side SQL injection
Impact
Sinks
Preventing
HTML5-storage manipulation
Sinks
Preventing
Client-side XPath injection
Impact
Sinks
Preventing
Client-side JSON injection
Impact
Sinks
Preventing
DOM-data manipulation
Impact
Sinks
Preventing
Denial of service
Sinks
Preventing
Web message vulnerabilities
Impact
Constructing an attack
Origin verification
Sinks
DOM clobbering
Exploiting
Preventing
Preventing vulnerabilities
View all DOM-based vulnerability labs
Web Security Academy DOM-based
DOM-based vulnerabilities
In this section, we will describe what the DOM is, explain how insecure processing of DOM data can introduce vulnerabilities, and suggest how you can prevent DOM-based vulnerabilities on your websites.
Labs
If you're already familiar with the basic concepts behind DOM-based vulnerabilities and just want to practice exploiting them on some realistic, deliberately vulnerable targets, you can access all of the labs in this topic from the link below.
View all DOM-based vulnerability labs What is the DOM?
The Document Object Model (DOM) is a web browser's hierarchical representation of the elements on the page. Websites can use JavaScript to manipulate the nodes and objects of the DOM, as well as their properties. DOM manipulation in itself is not a problem. In fact, it is an integral part of how modern websites work. However, JavaScript that handles data insecurely can enable various attacks. DOM-based vulnerabilities arise when a website contains JavaScript that takes an attacker-controllable value, known as a source, and passes it into a dangerous function, known as a sink.
Taint-flow vulnerabilities
Many DOM-based vulnerabilities can be traced back to problems with the way client-side code manipulates attacker-controllable data.
What is taint flow?
To either exploit or mitigate these vulnerabilities, it is important to first familiarize yourself with the basics of taint flow between sources and sinks.
Sources
A source is a JavaScript property that accepts data that is potentially attacker-controlled. An example of a source is the location.search property because it reads input from the query string, which is relatively simple for an attacker to control. Ultimately, any property that can be controlled by the attacker is a potential source. This includes the referring URL (exposed by the document.referrer string), the user's cookies (exposed by the document.cookie string), and web messages.
Sinks
A sink is a potentially dangerous JavaScript function or DOM object that can cause undesirable effects if attacker-controlled data is passed to it. For example, the eval() function is a sink because it processes the argument that is passed to it as JavaScript. An example of an HTML sink is document.body.innerHTML because it potentially allows an attacker to inject malicious HTML and execute arbitrary JavaScript.
Fundamentally, DOM-based vulnerabilities arise when a website passes data from a source to a sink, which then handles the data in an unsafe way in the context of the client's session.
The most common source is the URL, which is typically accessed with the location object. An attacker can construct a link to send a victim to a vulnerable page with a payload in the query string and fragment portions of the URL. Consider the following code:
goto = location.hash.slice(1)
if (goto.startsWith('https:')) {
&nbsp;&nbsp;location = goto;
}
This is vulnerable to DOM-based open redirection because the location.hash source is handled in an unsafe way. If the URL contains a hash fragment that starts with https: , this code extracts the value of the location.hash property and sets it as the location property of the window . An attacker could exploit this vulnerability by constructing the following URL:
https://www.innocent-website.com/example#https://www.evil-user.net
When a victim visits this URL, the JavaScript sets the value of the location property to https://www.evil-user.net , which automatically redirects the victim to the malicious site. This behavior could easily be exploited to construct a phishing attack, for example.
Common sources
The following are typical sources that can be used to exploit a variety of taint-flow vulnerabilities:
document.URL
document.documentURI
document.URLUnencoded
document.baseURI
location
document.cookie
document.referrer
window.name
history.pushState
history.replaceState
localStorage
sessionStorage
IndexedDB (mozIndexedDB, webkitIndexedDB, msIndexedDB)
Database
The following kinds of data can also be used as sources to exploit taint-flow vulnerabilities:
Reflected data LABS
Stored data LABS
Web messages LABS
Which sinks can lead to DOM-based vulnerabilities?
The following list provides a quick overview of common DOM-based vulnerabilities and an example of a sink that can lead to each one. For a more comprehensive list of relevant sinks, please refer to the vulnerability-specific pages by clicking the links below.
DOM-based vulnerability
Example sink
DOM XSS LABS
document.write()
Open redirection LABS
window.location
Cookie manipulation LABS
document.cookie
JavaScript injection
eval()
Document-domain manipulation
document.domain
WebSocket-URL poisoning
WebSocket()
Link manipulation
element.src
Web message manipulation
postMessage()
Ajax request-header manipulation
setRequestHeader()
Local file-path manipulation
FileReader.readAsText()
Client-side SQL injection
ExecuteSql()
HTML5-storage manipulation
sessionStorage.setItem()
Client-side XPath injection
document.evaluate()
Client-side JSON injection
JSON.parse()
DOM-data manipulation
element.setAttribute()
Denial of service
RegExp()
How to prevent DOM-based taint-flow vulnerabilities
There is no single action you can take to eliminate the threat of DOM-based attacks entirely. However, generally speaking, the most effective way to avoid DOM-based vulnerabilities is to avoid allowing data from any untrusted source to dynamically alter the value that is transmitted to any sink.
If the desired functionality of the application means that this behavior is unavoidable, then defenses must be implemented within the client-side code. In many cases, the relevant data can be validated on a whitelist basis, only allowing content that is known to be safe. In other cases, it will be necessary to sanitize or encode the data. This can be a complex task, and depending on the context into which the data is to be inserted, may involve a combination of JavaScript escaping, HTML encoding, and URL encoding, in the appropriate sequence.
For measures you can take to prevent specific vulnerabilities, please refer to the corresponding vulnerability pages linked from the table above.
DOM clobbering
DOM clobbering is an advanced technique in which you inject HTML into a page to manipulate the DOM and ultimately change the behavior of JavaScript on the website. The most common form of DOM clobbering uses an anchor element to overwrite a global variable, which is then used by the application in an unsafe way, such as generating a dynamic script URL.
Read more
DOM clobbering
Find DOM-based vulnerabilities using Burp Suite
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
