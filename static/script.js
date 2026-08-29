document.addEventListener("DOMContentLoaded", () => {

    const signupForm = document.getElementById("signupForm");

    if (signupForm) {

        signupForm.addEventListener("submit", (event) => {

            const password =
                document.getElementById("password").value;

            const confirmPassword =
                document.getElementById("confirm_password").value;

            if (password.length < 8) {

                event.preventDefault();

                alert(
                    "Password must contain at least 8 characters."
                );

                return;
            }

            if (password !== confirmPassword) {

                event.preventDefault();

                alert(
                    "Passwords do not match."
                );

            }

        });

    }


    const taskForms =
        document.querySelectorAll(".task-card form");

    taskForms.forEach((form) => {

        form.addEventListener("submit", (event) => {

            const confirmed = confirm(
                "Have you completed this task according to its instructions?"
            );

            if (!confirmed) {
                event.preventDefault();
            }

        });

    });


    setTimeout(() => {

        const alerts =
            document.querySelectorAll(
                ".alert, .dashboard-alert"
            );

        alerts.forEach((alert) => {

            alert.style.transition = "opacity .5s";

            alert.style.opacity = "0";

        });

    }, 6000);

});
