
# Create a personalised briefing


We are creating a personalised briefing for the following people:

- **Person 1:**
    - **Position**: Healthcare Policy Analyst
    - **Interests:** Healthcare reform, public health data, telemedicine, pharmaceutical innovation, health equity, government policy updates.
    - **Location:** USA
- **Person 2:**
    - **Position**: Tech Startup Founder
    - **Interests:** Artificial intelligence, venture capital, startup funding, SaaS trends, product management.
    - **Location:** London


You are given a file called `sources_06-05-25.json` containing many web sources on a variety of topics.

We have generated an OpenAI API key for you, for the sole purpose of assisting with this task. It is: [removed for security]

Please use:

- GPT-5.6 luna
- Any OpenAI embedding model


Feel free to use any libraries, frameworks etc that will help you accelerate and make your work production-ready

**Briefing requirements:**
- Backend should be a FastAPI server
- The frontend can be any framework (python or non python). You will not be judged on this.
- Content relevant to person's interests.
- Information should be up-to-date, nothing more than 1 month older than the newest source published date (06/05/25, i.e. 6th May 2025, DD/MM/YY).
- Markdown response
- Reference sources


**Extension**
Once you have finished your briefing program, create a [skill](https://agentskills.io/home) which can be called by a coding agent which can test your application


**Instructions:**
- Give some instructions in the `README` on how to run your program
- Program should be in standard python (no notebooks)
- Share a private Github repository once finished