$(function() {
    function WebDavBackupViewModel(parameters) {
        var self = this;

        self.settings = parameters[0];

        self.busy = ko.observable(false);
        
        self.testConnection = function() {
            self.busy(true);
            $.ajax({
                url: API_BASEURL + "plugin/webdavbackup",
                type: "POST",
                dataType: "json",
                data: JSON.stringify({
                    command: "test_connection",
                    server: self.settings.settings.plugins.webdavbackup.server(),
                    username: self.settings.settings.plugins.webdavbackup.username(),
                    password: self.settings.settings.plugins.webdavbackup.password(),
                    timeout: self.settings.settings.plugins.webdavbackup.timeout(),
                    verify_certificate: self.settings.settings.plugins.webdavbackup.verify_certificate()
                }),
                contentType: "application/json; charset=UTF-8",
                success: function(response) {
                    self.busy(false);
                    if (response.result) {
                        new PNotify({
                            title: gettext("Test succeeded"),
                            text: gettext("Connection test has succeeded."),
                            type: "success"
                        });
                    } else {
                        var text;
                        if (response.error === "credentials") {
                            text = gettext("Connection test failed, due to invalid credentials");
                        } else if (response.error === "server") {
                            text = gettext("Connection test failed, due to a server error");
                        } else {
                            text = gettext("Connection test failed, due to an unknown error. Please double check your settings and consult your log files.");
                        }
                        new PNotify({
                            title: gettext("Test failed"),
                            text: text,
                            type: "error"
                        });
                    }
                },
                error: function() {
                    self.busy(false);
                }
            });
        };
    }

    ADDITIONAL_VIEWMODELS.push([
        WebDavBackupViewModel,
        ["settingsViewModel"],
        ["#settings_plugin_webdavbackup"]
    ]);
});