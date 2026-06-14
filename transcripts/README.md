AI Transcript — Claude (Anthropic)

This transcript summarizes how AI was used during the development of the BhuMe assignment. AI was primarily used as a research, debugging, and technical guidance tool. The final approach, implementation decisions, testing, documentation, and submission preparation were carried out by me.

1. Understanding the Assignment

I initially shared the assignment links and preparation material with Claude to better understand the problem statement and evaluation criteria.

Claude helped me:

Understand the objective of aligning official plot boundaries with real-world field boundaries.
Interpret domain-specific terms such as plot, survey number, 7/12 extract, pot-kharaba, and georeferencing drift.
Break down the scoring methodology and output requirements.
Create a roadmap for approaching the task.

Based on this analysis, I planned my implementation strategy and project structure.

2. Reviewing the Dataset

After downloading the provided files, I inspected the dataset and starter-kit components.

During this phase, AI assisted me in:

Understanding the structure of input.geojson.
Understanding helper functions provided in the starter kit.
Interpreting metadata fields such as recorded area and mapped area.
Identifying possible indicators that could distinguish placement errors from geometry/area errors.

Using this information, I explored the data and decided on the features and heuristics to use in the solution.

3. Investigating Data Quality Issues

While working with the provided files, I noticed that some downloads appeared incomplete.

Using AI-assisted debugging, I:

Verified file formats.
Examined TIFF metadata.
Confirmed that portions of the imagery dataset were unavailable due to incomplete downloads.
Documented these limitations for transparency in the final submission.

The decision to proceed with available imagery and clearly mention the limitation was made by me.

4. Developing the Alignment Strategy

I designed and iteratively improved the boundary-alignment pipeline.

AI was used as a technical sounding board while I experimented with different approaches.

The final method included:

Area-Ratio Analysis

I analyzed the relationship between:

Recorded area
Mapped area

This helped identify plots that were likely suffering from:

Positioning errors (correctable)
Area inconsistencies (unlikely to be corrected by shifting)
Image-Based Alignment

I implemented a boundary-matching approach using image patches extracted around each plot.

During development:

I experimented with different boundary representations.
I evaluated correlation-based matching methods.
I improved performance using FFT-based techniques.

AI helped explain implementation options, while I selected and tested the final approach.

5. Debugging and Refinement

During testing, I encountered several issues.

Examples included:

Incorrect confidence behavior.
Logic errors in result counting.
Formatting bugs that affected processing.

I used Claude to help identify potential causes, after which I corrected the implementation and verified the fixes through additional testing.

6. Spatial Consistency Improvements

After observing some incorrect alignments, I introduced a spatial-consensus step.

The idea was to:

Compare each plot's estimated shift with nearby plots.
Detect obvious outliers.
Replace unreliable shifts with neighborhood-consensus values when appropriate.

AI helped discuss possible strategies, but the integration and evaluation of this refinement were performed by me as part of the final pipeline.

7. Confidence Scoring

I designed a confidence score using multiple signals, including:

Alignment strength
Area consistency
Spatial agreement with neighboring plots

I experimented with different weight combinations and used AI to review the formulation and suggest improvements.

The final confidence calculation was selected based on my own testing and observations.

8. Validation and Quality Checks

Before finalizing the submission, I:

Ran the pipeline on all plots.
Checked geometry validity.
Investigated problematic cases.
Reviewed alignment results visually.
Generated diagnostic outputs for manual inspection.

AI assisted with debugging suggestions and validation ideas during this stage.

9. Documentation and Packaging

Once the solution was finalized, I prepared:

Project documentation
Methodology explanation
Video presentation notes
Submission package
GitHub repository

AI helped improve the clarity of documentation and presentation materials, but all project artifacts were reviewed and finalized by me.

Summary of AI Usage

AI was used as:

A technical research assistant
A debugging assistant
A documentation assistant
A brainstorming tool

The final solution, implementation decisions, experimentation, testing, evaluation, documentation review, GitHub submission, and overall project ownership remained my responsibility.

